import { useEffect, useState } from "react";
import { MapContainer, TileLayer, Marker, Popup, GeoJSON, useMapEvents } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import "leaflet/dist/leaflet.css";
import L from "leaflet";

// Fix for default Leaflet icon issues in Vite
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

interface RegionData {
  id: string;
  name: string;
  governorate: string;
  lat: number;
  lng: number;
  en_attente: number;
  en_cours: number;
  interprete: number;
}

function MapEventHandler({ onMapClick }: { onMapClick: () => void }) {
  useMapEvents({
    click: () => onMapClick(),
  });
  return null;
}

export default function MapView({
  regions,
  selectedRegionId,
  setSelectedRegionId,
}: {
  regions: RegionData[];
  selectedRegionId: string | null;
  setSelectedRegionId: (id: string | null) => void;
}) {
  const [geoData, setGeoData] = useState<any>(null);

  useEffect(() => {
    fetch("https://raw.githubusercontent.com/johan/world.geo.json/master/countries/TUN.geo.json")
      .then((res) => res.json())
      .then((data) => {
        if (data.features && data.features.length > 0) {
          const tunisiaCoords = data.features[0].geometry.coordinates;
          const invertedGeoJSON = {
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                properties: {},
                geometry: {
                  type: "Polygon",
                  coordinates: [
                    [
                      [-180, 90],
                      [-180, -90],
                      [180, -90],
                      [180, 90],
                      [-180, 90],
                    ],
                    ...tunisiaCoords,
                  ],
                },
              },
            ],
          };
          setGeoData(invertedGeoJSON);
        }
      })
      .catch((err) => console.error("Error loading GeoJSON", err));
  }, []);

  // Custom Div Icon Creator
  const createCustomIcon = (totalExams: number, interprete: number, name: string, isSelected: boolean) => {
    const siteAverage = totalExams / 3;
    const isAboveAverage = interprete > siteAverage;
    const colorClass = isAboveAverage ? "bg-emerald-500" : "bg-red-500";
    const borderClass = isSelected
      ? "ring-[3px] ring-blue-700 ring-offset-2 ring-offset-white scale-110"
      : "ring-2 ring-white";

    return L.divIcon({
      html: `
        <div class="relative flex flex-col items-center justify-center -mt-5">
          <div class="h-9 min-w-9 rounded-md ${colorClass} ${borderClass} px-2 shadow-[0_10px_20px_rgba(15,23,42,0.18)] transition-all flex items-center justify-center text-white font-semibold text-[13px]" style="font-family: Inter, 'Helvetica Neue', Arial, sans-serif;">
            ${totalExams}
          </div>
          <div class="bg-white px-2 py-1 mt-1 rounded-md text-[11px] font-semibold text-slate-800 shadow-sm whitespace-nowrap border border-slate-200">
            ${name}
          </div>
        </div>
      `,
      className: "",
      iconSize: [56, 64],
      iconAnchor: [28, 32],
    });
  };

  return (
    <MapContainer
      center={[34.25, 9.65]}
      zoom={7}
      minZoom={6.5}
      maxZoom={18}
      zoomSnap={0.5}
      zoomControl={true}
      attributionControl={false}
      maxBounds={[
        [30.0, 7.0], // Limite Sud-Ouest
        [37.8, 12.2], // Limite Nord-Est
      ]}
      maxBoundsViscosity={1.0}
      scrollWheelZoom={true}
      dragging={true}
      className="w-full h-full"
    >
      <MapEventHandler onMapClick={() => setSelectedRegionId(null)} />
      <style>
        {`
          .leaflet-bar {
              border: none !important;
              box-shadow: 0 8px 20px rgba(15,23,42,0.12) !important;
          }
          .leaflet-bar a {
              background-color: #ffffff !important;
              color: #0f172a !important;
              border-bottom: 1px solid #e2e8f0 !important;
          }
          .leaflet-popup-content-wrapper {
              border-radius: 8px !important;
              box-shadow: 0 16px 32px rgba(15,23,42,0.18) !important;
          }
          .leaflet-popup-content {
              margin: 12px 14px !important;
          }
        `}
      </style>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
        url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
      />
      <MarkerClusterGroup
        chunkedLoading
        maxClusterRadius={40}
        spiderfyOnMaxZoom={true}
        showCoverageOnHover={false}
        iconCreateFunction={(cluster: any) => {
          const clusterTotal = cluster
            .getAllChildMarkers()
            .reduce((sum: number, marker: any) => sum + Number(marker.options.title || 0), 0);

          return L.divIcon({
            html: `
              <div class="w-[45px] h-[45px] rounded-full bg-blue-500/20 flex items-center justify-center">
                <div class="w-[35px] h-[35px] bg-slate-900 text-white font-semibold text-[13px] rounded-md flex items-center justify-center shadow-[0_8px_18px_rgba(15,23,42,0.2)]" style="font-family: Inter, 'Helvetica Neue', Arial, sans-serif;">
                  ${clusterTotal}
                </div>
              </div>
            `,
            className: "",
            iconSize: [45, 45],
          });
        }}
      >
        {regions.map((region) => {
          const totalExams = region.en_attente + region.en_cours + region.interprete;
          const siteAverage = totalExams / 3;
          const isAboveAverage = region.interprete > siteAverage;

          return (
            <Marker
              key={region.id}
              position={[region.lat, region.lng]}
              title={String(totalExams)}
              icon={createCustomIcon(totalExams, region.interprete, region.name, selectedRegionId === region.id)}
              eventHandlers={{
                click: () => {
                  setSelectedRegionId(region.id === selectedRegionId ? null : region.id);
                },
              }}
            >
              <Popup>
                <div className="min-w-44">
                  <strong className="block text-sm text-slate-950">{region.name}</strong>
                  <span className="text-xs text-slate-500">{region.governorate}</span>
                  <div className="mt-3 rounded-md bg-slate-50 px-3 py-2">
                    <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                      Total examens filtrés
                    </div>
                    <div className="mt-1 text-lg font-semibold tabular-nums text-slate-950">{totalExams}</div>
                    <div className={`mt-1 text-xs font-medium ${isAboveAverage ? "text-emerald-600" : "text-red-600"}`}>
                      {region.interprete} interprétés / moyenne du site : {siteAverage.toFixed(1)}
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                    <div>
                      <div className="text-[10px] uppercase text-slate-400">Attente</div>
                      <div className="font-semibold text-orange-600">{region.en_attente}</div>
                    </div>
                    <div>
                      <div className="text-[10px] uppercase text-slate-400">Cours</div>
                      <div className="font-semibold text-blue-600">{region.en_cours}</div>
                    </div>
                    <div>
                      <div className="text-[10px] uppercase text-slate-400">Interpr.</div>
                      <div className="font-semibold text-emerald-600">{region.interprete}</div>
                    </div>
                  </div>
                </div>
              </Popup>
            </Marker>
          );
        })}
      </MarkerClusterGroup>
    </MapContainer>
  );
}
