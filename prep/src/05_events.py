"""Etapa 05 — incendios -> eventos (estilo FEDS).

Enlace progresivo por pass_bin:
- buffer 1 km, o 5 km si el evento está en AP y es bosque;
- un incendio se une si algún hotspot toca (d <= r_i+r_j+buffer) un hotspot
  del evento detectado en los últimos 5 días;
- fusión de eventos conservando el evento más antiguo;
- cierre a los 5 días sin incendios nuevos.

Salidas:
  prep/data/interim/05_events_core.parquet
  prep/data/interim/05_eventos_interim.parquet   (>=1 incendio argentino)
  prep/data/interim/05_fire_event_map.parquet
  prep/data/interim/05_event_merge_audit.parquet
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geo  # noqa: E402
import ids  # noqa: E402
from common import RunContext, write_parquet_atomic  # noqa: E402

EVENT_SCHEMA = pa.schema([
    ("evento_id", pa.string()),
    ("inicio", pa.timestamp("us")),
    ("fin", pa.timestamp("us")),
    ("duracion_dias", pa.float64()),
    ("n_incendios", pa.int64()),
    ("n_incendios_total", pa.int64()),
    ("incendios_argentina", pa.int64()),
    ("n_pass_bins_activos", pa.int64()),
    ("area_pixeles_km2", pa.float64()),
    ("area_poligono_km2", pa.float64()),
    ("en_area_protegida", pa.bool_()),
    ("es_bosque", pa.bool_()),
    ("buffer_km", pa.float64()),
    ("lc_clase", pa.int16()),
    ("lc_metodo", pa.string()),
    ("geometry_wkb", pa.binary()),
    ("incendios", pa.string()),
])

MAP_SCHEMA = pa.schema([
    ("incendio_id", pa.string()),
    ("evento_id", pa.string()),
])


@dataclass
class EventState:
    event_id: str
    seed_ts: pd.Timestamp
    start: pd.Timestamp
    end: pd.Timestamp
    last_ts: pd.Timestamp
    fires: list[int] = field(default_factory=list)
    area_pix: float = 0.0
    ap: bool = False
    lc_weights: dict[int, float] = field(default_factory=dict)
    n_ar: int = 0
    buffer_m: float = 1000.0
    closed: bool = False

    def forest(self, forest_classes: set[int]) -> bool:
        if not self.lc_weights:
            return False
        return max(self.lc_weights, key=self.lc_weights.get) in forest_classes

    def majority_class(self) -> int:
        if not self.lc_weights:
            return -1
        return int(max(self.lc_weights, key=self.lc_weights.get))


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def add(self, idx: int) -> None:
        self.parent.setdefault(idx, idx)

    def find(self, idx: int) -> int:
        parent = self.parent.setdefault(idx, idx)
        while parent != idx:
            idx, parent = parent, self.parent.setdefault(parent, parent)
        return idx

    def union(self, a: int, b: int) -> int:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return ra
        self.parent[rb] = ra
        return ra


def bin_start_utc(label: str, cfg: dict) -> pd.Timestamp:
    date_part, suffix = label[:-2], label[-1]
    hour = int(cfg["pass_bin"]["day_start_hour"] if suffix == cfg["pass_bin"]["day_label"]
               else cfg["pass_bin"]["night_start_hour"])
    local = pd.Timestamp(date_part) + pd.Timedelta(hours=hour)
    return local - pd.Timedelta(hours=int(cfg["pass_bin"]["utc_offset_hours"]))


def load_inputs(ctx: RunContext) -> dict:
    cfg = ctx.cfg
    fires = pd.read_parquet(ctx.interim("04_fires_core.parquet"))
    lc = pd.read_parquet(ctx.interim("04_fire_landcover.parquet"),
                         columns=["incendio_id", "lc_clase", "es_bosque"])
    fires = fires.merge(lc, on="incendio_id", how="left")
    fires["lc_clase"] = fires["lc_clase"].fillna(-1).astype(int)
    fires["es_bosque"] = fires["es_bosque"].fillna(False).astype(bool)
    fires = fires.sort_values(["pass_bin", "t_inicio", "incendio_id"],
                              kind="stable").reset_index(drop=True)
    fires["fire_idx"] = np.arange(len(fires), dtype=np.int64)
    fires["bin_start_utc"] = fires["pass_bin"].map(lambda b: bin_start_utc(b, cfg))

    fire_idx = fires.set_index("incendio_id")["fire_idx"]
    fmap = pd.read_parquet(ctx.interim("04_fire_hotspot_map.parquet"))
    fmap["fire_idx"] = fmap["incendio_id"].map(fire_idx)
    if fmap["fire_idx"].isna().any():
        raise RuntimeError("hotspots sin incendio en el mapa")
    fmap["fire_idx"] = fmap["fire_idx"].astype(np.int64)

    hs = pd.read_parquet(ctx.interim("03_hotspots_classified.parquet"),
                         columns=["hotspot_pk", "x", "y", "r_m", "ts_utc"])
    hot = fmap.merge(hs, on="hotspot_pk", how="left", validate="many_to_one")
    hot = hot.sort_values(["fire_idx", "ts_utc"], kind="stable").reset_index(drop=True)
    if hot[["x", "y", "r_m", "ts_utc"]].isna().any().any():
        raise RuntimeError("hotspots sin geometría/tiempo en el mapa")
    hot["ts_ns"] = pd.to_datetime(hot["ts_utc"]).astype("datetime64[ns]").astype("int64")
    counts = np.bincount(hot["fire_idx"].to_numpy(), minlength=len(fires) + 1)
    offsets = np.zeros(len(fires) + 1, dtype=np.int64)
    np.cumsum(counts[:-1], out=offsets[1:])
    if offsets[-1] != len(hot):
        raise RuntimeError("offsets de hotspots inconsistentes")

    return {
        "fires": fires,
        "hx": hot["x"].to_numpy(dtype=float),
        "hy": hot["y"].to_numpy(dtype=float),
        "hr": hot["r_m"].to_numpy(dtype=float),
        "hts": hot["ts_ns"].to_numpy(dtype=np.int64),
        "offsets": offsets,
        "n_fires": len(fires),
    }


def main(argv: list[str] | None = None) -> int:
    ctx = RunContext.from_cli("05_events", argv)
    try:
        cfg = ctx.cfg
        data = load_inputs(ctx)
        fires = data["fires"]
        n_fires = data["n_fires"]
        hx, hy, hr, hts = data["hx"], data["hy"], data["hr"], data["hts"]
        offsets = data["offsets"]

        f_bin = fires["pass_bin"].to_numpy()
        f_bin_start = pd.to_datetime(fires["bin_start_utc"]).astype("datetime64[ns]")
        f_t0 = pd.to_datetime(fires["t_inicio"]).astype("datetime64[ns]")
        f_t1 = pd.to_datetime(fires["t_fin"]).astype("datetime64[ns]")
        f_area = fires["area_pixeles_km2"].to_numpy(dtype=float)
        f_ar = fires["en_argentina"].to_numpy(dtype=bool)
        f_ap = fires["en_area_protegida"].to_numpy(dtype=bool)
        f_lc = fires["lc_clase"].to_numpy(dtype=int)
        f_es_bosque = fires["es_bosque"].to_numpy(dtype=bool)
        f_id = fires["incendio_id"].to_numpy()
        f_wkb = fires["geometry_wkb"].to_numpy()
        f_ts0 = f_t0.astype("int64").to_numpy()
        f_ts1 = f_t1.astype("int64").to_numpy()
        f_bin_start_ns = f_bin_start.astype("int64").to_numpy()

        forest_classes = set(int(c) for c in cfg["aux"]["landcover"]["forest_classes"])
        buffer_default = float(cfg["events"]["buffer_km"]["default"]) * 1000.0
        buffer_prot = float(cfg["events"]["buffer_km"]["protected_forest"]) * 1000.0
        buffer_max = max(buffer_default, buffer_prot)
        inactivity_ns = int(cfg["events"]["inactivity_days"]) * 24 * 3600 * 10**9
        link_window_ns = int(cfg["events"]["link_window_days"]) * 24 * 3600 * 10**9

        def new_state(fire_idx: int) -> EventState:
            ts = pd.Timestamp(f_t0[fire_idx])
            state = EventState(
                event_id=ids.event_id(str(f_id[fire_idx]), ts),
                seed_ts=ts, start=ts, end=pd.Timestamp(f_t1[fire_idx]), last_ts=ts,
            )
            add_fire(state, fire_idx)
            return state

        def add_fire(state: EventState, fire_idx: int) -> None:
            state.fires.append(fire_idx)
            state.area_pix += float(f_area[fire_idx])
            state.ap = state.ap or bool(f_ap[fire_idx])
            cl = int(f_lc[fire_idx])
            if cl >= 0:
                state.lc_weights[cl] = state.lc_weights.get(cl, 0.0) + float(f_area[fire_idx])
            state.n_ar += int(f_ar[fire_idx])
            state.start = min(state.start, pd.Timestamp(f_t0[fire_idx]))
            state.end = max(state.end, pd.Timestamp(f_t1[fire_idx]))
            state.last_ts = max(state.last_ts, pd.Timestamp(f_t1[fire_idx]))
            state.buffer_m = buffer_prot if (state.ap and state.forest(forest_classes)) else buffer_default

        def merge_states(survivor: EventState, absorbed: EventState) -> None:
            survivor.fires.extend(absorbed.fires)
            survivor.area_pix += absorbed.area_pix
            survivor.ap = survivor.ap or absorbed.ap
            for cl, w in absorbed.lc_weights.items():
                survivor.lc_weights[cl] = survivor.lc_weights.get(cl, 0.0) + w
            survivor.n_ar += absorbed.n_ar
            survivor.start = min(survivor.start, absorbed.start)
            survivor.end = max(survivor.end, absorbed.end)
            survivor.last_ts = max(survivor.last_ts, absorbed.last_ts)
            survivor.buffer_m = buffer_prot if (survivor.ap and survivor.forest(forest_classes)) else buffer_default

        uf = UnionFind()
        states: dict[int, EventState] = {}
        active: set[int] = set()
        fire_event = np.full(n_fires, -1, dtype=np.int64)
        next_event = 0
        event_rows: list[dict] = []
        map_rows: list[dict] = []
        merge_audit: list[dict] = []
        n_merges = 0
        n_closed = 0

        def write_event(idx: int) -> None:
            nonlocal n_closed
            state = states[idx]
            if state.closed:
                return
            fire_list = state.fires
            geoms = [shapely.from_wkb(f_wkb[i]) for i in fire_list]
            geom = shapely.union_all(geoms) if len(geoms) > 1 else geoms[0]
            area_poly = float(shapely.area(geom)) / 1e6
            dur = (state.end - state.start).total_seconds() / 86400.0
            lc_cls = state.majority_class()
            es_bosque = lc_cls in forest_classes
            event_rows.append({
                "evento_id": state.event_id,
                "inicio": state.start,
                "fin": state.end,
                "duracion_dias": float(dur),
                "n_incendios": int(len(fire_list)),
                "n_incendios_total": int(len(fire_list)),
                "incendios_argentina": int(state.n_ar),
                "n_pass_bins_activos": int(len({str(f_bin[i]) for i in fire_list})),
                "area_pixeles_km2": float(state.area_pix),
                "area_poligono_km2": area_poly,
                "en_area_protegida": bool(state.ap),
                "es_bosque": bool(es_bosque),
                "buffer_km": float(state.buffer_m / 1000.0),
                "lc_clase": int(lc_cls),
                "lc_metodo": "fire_area_weighted" if len(fire_list) > 1 else "single_fire",
                "geometry_wkb": shapely.to_wkb(geom),
                "incendios": ",".join(str(f_id[i]) for i in sorted(fire_list, key=lambda i: (f_t0[i], f_id[i]))),
            })
            for i in fire_list:
                map_rows.append({"incendio_id": str(f_id[i]), "evento_id": state.event_id})
            state.closed = True
            n_closed += 1

        # Agrupar por pass_bin en orden temporal.
        bin_order = (fires[["pass_bin", "bin_start_utc"]].drop_duplicates()
                     .sort_values("bin_start_utc"))
        for bin_name in bin_order["pass_bin"]:
            bin_fires = fires.index[fires["pass_bin"] == bin_name].to_numpy()
            if len(bin_fires) == 0:
                continue
            bstart = pd.Timestamp(fires.loc[bin_fires[0], "bin_start_utc"])
            bstart_ns = int(bstart.value)

            # Cerrar eventos inactivos.
            for idx in list(active):
                if states[idx].last_ts < bstart - pd.Timedelta(nanoseconds=inactivity_ns):
                    write_event(idx)
                    active.discard(idx)

            # Índice de hotspots: eventos activos + todos los del bin actual.
            ax, ay, ar, ats, aev, afire, aorder = [], [], [], [], [], [], []
            for idx in active:
                for fi in states[idx].fires:
                    lo, hi = offsets[fi], offsets[fi + 1]
                    if hi <= lo:
                        continue
                    take = hts[lo:hi] >= bstart_ns - link_window_ns
                    if not take.any():
                        continue
                    ax.append(hx[lo:hi][take]); ay.append(hy[lo:hi][take])
                    ar.append(hr[lo:hi][take]); ats.append(hts[lo:hi][take])
                    aev.append(np.full(int(take.sum()), idx, dtype=np.int64))
                    afire.append(np.full(int(take.sum()), fi, dtype=np.int64))
                    aorder.append(np.full(int(take.sum()), -1, dtype=np.int64))
            for order, fi in enumerate(bin_fires):
                lo, hi = offsets[fi], offsets[fi + 1]
                if hi <= lo:
                    continue
                ax.append(hx[lo:hi]); ay.append(hy[lo:hi])
                ar.append(hr[lo:hi]); ats.append(hts[lo:hi])
                aev.append(np.full(hi - lo, -1, dtype=np.int64))
                afire.append(np.full(hi - lo, fi, dtype=np.int64))
                aorder.append(np.full(hi - lo, order, dtype=np.int64))

            if ax:
                AX = np.concatenate(ax); AY = np.concatenate(ay)
                AR = np.concatenate(ar); ATS = np.concatenate(ats)
                AEV = np.concatenate(aev); AFIRE = np.concatenate(afire)
                AORDER = np.concatenate(aorder)
                tree = cKDTree(np.column_stack([AX, AY]))
                r_max_active = float(AR.max())
            else:
                tree = None
                r_max_active = 0.0

            for order, fi in enumerate(bin_fires):
                lo, hi = offsets[fi], offsets[fi + 1]
                touched: set[int] = set()
                if tree is not None and hi > lo:
                    tmin = f_ts0[fi] - link_window_ns
                    for k in range(lo, hi):
                        radius = float(hr[k]) + r_max_active + buffer_max + 1.0
                        cand = tree.query_ball_point((hx[k], hy[k]), radius)
                        if not cand:
                            continue
                        cand = np.asarray(cand, dtype=np.int64)
                        # descartar el propio hotspot/fire
                        cand = cand[AFIRE[cand] != fi]
                        if cand.size == 0:
                            continue
                        # ventana temporal
                        cand = cand[ATS[cand] >= tmin]
                        if cand.size == 0:
                            continue
                        # orden progresivo dentro del bin
                        if (AORDER[cand] >= 0).any():
                            keep = (AORDER[cand] < 0) | (AORDER[cand] < order)
                            cand = cand[keep]
                            if cand.size == 0:
                                continue
                        # evento del candidato
                        for j in cand:
                            ci = int(AFIRE[j])
                            ev = int(AEV[j])
                            if ev < 0:
                                ev = int(fire_event[ci])
                                if ev < 0:
                                    continue
                            ev = uf.find(ev)
                            if ev not in active:
                                continue
                            d = float(np.hypot(hx[k] - AX[j], hy[k] - AY[j]))
                            if d <= float(hr[k]) + float(AR[j]) + states[ev].buffer_m:
                                touched.add(ev)
                                break  # un hotspot alcanza para tocar el evento

                if not touched:
                    idx = next_event
                    next_event += 1
                    uf.add(idx)
                    states[idx] = new_state(int(fi))
                    fire_event[fi] = idx
                    active.add(idx)
                elif len(touched) == 1:
                    idx = next(iter(touched))
                    add_fire(states[idx], int(fi))
                    fire_event[fi] = idx
                else:
                    roots = sorted({uf.find(i) for i in touched},
                                   key=lambda i: (states[i].seed_ts, states[i].event_id))
                    survivor = roots[0]
                    add_fire(states[survivor], int(fi))
                    fire_event[fi] = survivor
                    for absorbed in roots[1:]:
                        merge_states(states[survivor], states[absorbed])
                        uf.union(survivor, absorbed)
                        active.discard(absorbed)
                        n_merges += 1
                        merge_audit.append({
                            "bin": bin_name,
                            "evento_survivor": states[survivor].event_id,
                            "evento_absorbido": states[absorbed].event_id,
                            "n_incendios_survivor": len(states[survivor].fires),
                            "n_incendios_absorbido": len(states[absorbed].fires),
                        })
                    active.add(survivor)

        for idx in list(active):
            write_event(idx)
        # Eventos que quedaron fuera de active pero no cerrados (por fusión) no
        # se escriben: sus incendios viven en el superviviente.

        events = pd.DataFrame(event_rows)
        if len(events):
            events = events.sort_values(["inicio", "evento_id"], kind="stable").reset_index(drop=True)
        events_path = ctx.interim("05_events_core.parquet")
        if len(events):
            write_parquet_atomic(events, events_path)
        else:
            pq.write_table(pa.Table.from_pylist([], schema=EVENT_SCHEMA), events_path)
        maps = pd.DataFrame(map_rows, columns=["incendio_id", "evento_id"])
        write_parquet_atomic(maps, ctx.interim("05_fire_event_map.parquet"))
        audit = pd.DataFrame(merge_audit)
        write_parquet_atomic(audit, ctx.interim("05_event_merge_audit.parquet"))

        interim = events[events["incendios_argentina"] > 0].copy() if len(events) else events
        write_parquet_atomic(interim, ctx.interim("05_eventos_interim.parquet"))

        ctx.stats.add("events.total", int(len(events)))
        ctx.stats.add("events.argentina", int(len(interim)))
        ctx.stats.add("events.merged", int(n_merges))
        ctx.stats.add("events.closed", int(n_closed))
        ctx.stats.add("events.singletons", int((events["n_incendios"] == 1).sum()) if len(events) else 0)
        ctx.stats.add("events.singleton_fraction",
                      float((events["n_incendios"] == 1).mean()) if len(events) else 0.0)
        ctx.stats.add("events.max_fires", int(events["n_incendios"].max()) if len(events) else 0)
        ctx.stats.add("events.max_area_km2", float(events["area_poligono_km2"].max()) if len(events) else 0.0)
        ctx.stats.table("events.top_by_fires",
                        events.nlargest(20, "n_incendios")[
                            ["evento_id", "inicio", "fin", "n_incendios",
                             "area_poligono_km2", "en_area_protegida", "es_bosque"]
                        ].to_dict("records") if len(events) else [])
        ctx.stats.flush()
        ctx.log.info("Etapa 05 OK: %d eventos (%d Argentina), %d fusiones",
                     len(events), len(interim), n_merges)
        return 0
    except Exception as exc:  # noqa: BLE001
        ctx.log.exception("Etapa 05 falló: %s", exc)
        ctx.stats.warn(str(exc))
        ctx.stats.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
