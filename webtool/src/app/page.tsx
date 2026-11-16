import { Suspense } from 'react';
import MapView from '@/components/MapView';

export default function MapPage() {
  return (
    <div className="map-page">
      <Suspense fallback={null}>
        <MapView />
      </Suspense>
    </div>
  );
}
