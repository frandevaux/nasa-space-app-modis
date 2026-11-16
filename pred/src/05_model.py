"""Modelo CNN + LSTM para predecir hotspots en 7 días.

Entrada: historia 14 días (20 canales), clima futuro 7 días (7 canales),
estáticos 12 canales y un vector del hotspot ancla (17).
Salida: logits (B, 7, 32, 32).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


class ConvBlock(nn.Module):
    def __init__(self, cin: int, cout: int, stride: int = 1):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(cin, cout, 3, stride=stride, padding=1, bias=False),
            nn.BatchNorm2d(cout),
            nn.ReLU(inplace=True),
        )

    def forward(self, x):
        return self.net(x)


class HotspotCNN(nn.Module):
    def __init__(self, c_hist: int = 20, c_fut: int = 7, c_static: int = 12,
                 d_vec: int = 17, hidden: int = 64, horizon: int = 7,
                 dropout: float = 0.3):
        super().__init__()
        self.c_hist = c_hist
        self.c_fut = c_fut
        self.c_static = c_static
        self.horizon = horizon
        self.hidden = hidden

        # Encoder de historia (+ estáticos repetidos).
        self.enc = nn.Sequential(
            ConvBlock(c_hist + c_static, 32, 1),
            ConvBlock(32, 64, 2),   # 16x16
            ConvBlock(64, 64, 2),   # 8x8
        )
        self.lstm = nn.LSTM(input_size=64 * 8 * 8, hidden_size=hidden,
                            num_layers=1, batch_first=True, dropout=0.0)

        # Encoder de clima futuro (+ estáticos).
        self.fut = nn.Sequential(
            ConvBlock(c_fut + c_static, 32, 1),
            ConvBlock(32, 64, 2),
            ConvBlock(64, 64, 2),
        )
        self.fut_fc = nn.Linear(64 * 8 * 8, hidden)

        self.vec = nn.Sequential(
            nn.Linear(d_vec, 64), nn.ReLU(inplace=True),
            nn.Linear(64, 64), nn.ReLU(inplace=True),
        )
        self.day = nn.Embedding(horizon, 16)
        self.drop = nn.Dropout(dropout)

        # Decoder compartido por día futuro.
        self.dec_fc = nn.Linear(hidden + 64 + hidden + 16, 64 * 8 * 8)
        self.dec_up1 = nn.ConvTranspose2d(64, 64, 4, stride=2, padding=1)
        self.dec_conv1 = nn.Sequential(
            nn.Conv2d(128, 64, 3, padding=1, bias=False),
            nn.BatchNorm2d(64), nn.ReLU(inplace=True),
        )
        self.dec_up2 = nn.ConvTranspose2d(64, 64, 4, stride=2, padding=1)
        self.dec_conv2 = nn.Sequential(
            nn.Conv2d(64, 64, 3, padding=1, bias=False),
            nn.BatchNorm2d(64), nn.ReLU(inplace=True),
        )
        self.out = nn.Conv2d(64, 1, 1)

        self._init_weights()

    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, (nn.Conv2d, nn.ConvTranspose2d, nn.Linear)):
                nn.init.kaiming_normal_(m.weight, nonlinearity="relu")
                if getattr(m, "bias", None) is not None:
                    nn.init.zeros_(m.bias)
        # Salida cerca de probabilidad baja inicial.
        nn.init.constant_(self.out.bias, -3.0)

    def forward(self, x_hist, x_fut, x_static, v):
        B, T, C, H, W = x_hist.shape
        Fh = x_fut.shape[1]
        st = x_static.unsqueeze(1).expand(-1, T, -1, -1, -1)
        enc_in = torch.cat([x_hist, st], dim=2).reshape(B * T, C + self.c_static, H, W)
        f1 = self.enc[0](enc_in)
        f2 = self.enc[1](f1)   # 16x16
        f3 = self.enc[2](f2)   # 8x8
        # Skip del último frame de historia.
        skip = f2.reshape(B, T, 64, 16, 16)[:, -1]
        seq = f3.reshape(B, T, 64 * 8 * 8)
        h, _ = self.lstm(seq)
        h_t = h[:, -1]

        stf = x_static.unsqueeze(1).expand(-1, Fh, -1, -1, -1)
        fut_in = torch.cat([x_fut, stf], dim=2).reshape(B * Fh, self.c_fut + self.c_static, H, W)
        w = self.fut(fut_in).reshape(B * Fh, 64 * 8 * 8)
        w = self.fut_fc(w).reshape(B, Fh, self.hidden)

        ve = self.vec(v)
        outs = []
        for lead in range(Fh):
            day = self.day.weight[lead].unsqueeze(0).expand(B, -1)
            cond = torch.cat([h_t, ve, w[:, lead], day], dim=1)
            z = self.drop(self.dec_fc(cond)).reshape(B, 64, 8, 8)
            z = self.dec_up1(z)            # 16x16
            z = self.dec_conv1(torch.cat([z, skip], dim=1))
            z = self.dec_up2(z)            # 32x32
            z = self.dec_conv2(z)
            outs.append(self.out(z))
        return torch.cat(outs, dim=1)      # (B, Fh, 32, 32)


def param_count(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def masked_bce(logits, y, mask, pos_weight: float = 75.0,
               gamma: float = 0.0) -> torch.Tensor:
    """BCE (o focal) enmascarada por provincia."""
    m = mask.unsqueeze(1)
    bce = F.binary_cross_entropy_with_logits(
        logits, y, reduction="none",
        pos_weight=torch.tensor(pos_weight, device=logits.device),
    )
    if gamma and gamma > 0:
        p = torch.sigmoid(logits)
        pt = torch.where(y > 0.5, p, 1 - p)
        bce = bce * (1 - pt).pow(gamma)
    return (bce * m).sum() / m.expand_as(bce).sum().clamp_min(1.0)


def patch_loss(logits, y, mask, eps: float = 1e-6) -> tuple[torch.Tensor, torch.Tensor]:
    """Si un parche/día tiene hotspots, castiga que el máximo sea bajo.

    Devuelve (loss, número de parches-día positivos).
    """
    p = torch.sigmoid(logits)
    m = mask.unsqueeze(1).expand_as(p)
    has = (y * m).sum(dim=(2, 3)) > 0.5  # (B, H)
    if has.sum() == 0:
        return logits.new_zeros(()), has.sum()
    # Máximo sobre las celdas que realmente tienen hotspot, no sobre todo el parche.
    pmax = (p * y).amax(dim=(2, 3))      # (B, H)
    loss = -torch.log(pmax[has].clamp_min(eps)).mean()
    return loss, has.sum()


@dataclass
class LossWeights:
    pos_weight: float = 75.0
    lambda_patch: float = 1.0
    gamma: float = 0.0
    lambda_count: float = 0.0


def compute_loss(model_out, y, y_count, mask, weights: LossWeights):
    bce = masked_bce(model_out, y, mask, pos_weight=weights.pos_weight,
                     gamma=weights.gamma)
    pl, npos = patch_loss(model_out, y, mask)
    total = bce + weights.lambda_patch * pl
    if weights.lambda_count > 0:
        p = torch.sigmoid(model_out)
        m = mask.unsqueeze(1)
        cnt = (p * m).sum(dim=(2, 3)) / m.sum(dim=(2, 3)).clamp_min(1.0)
        tgt = (y_count * m).sum(dim=(2, 3)) / m.sum(dim=(2, 3)).clamp_min(1.0)
        total = total + weights.lambda_count * F.mse_loss(cnt, tgt)
    return {"loss": total, "bce": bce, "patch": pl, "n_patch_pos": npos}
