import { MapContainer, TileLayer, Marker, Popup, Polygon, useMapEvents } from "react-leaflet";
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

// Contour simplifie de la Tunisie (lat, lng). Sert uniquement au masque de
// focus : la precision au kilometre n'est pas necessaire, la silhouette si.
const TUNISIA_OUTLINE: [number, number][] = [
  [37.05, 8.6], [37.2, 9.2], [37.34, 9.8], [37.16, 10.3], [37.08, 11.05],
  [36.75, 10.95], [36.45, 10.75], [35.85, 10.6], [35.5, 11.05], [35.05, 11.05],
  [34.72, 10.78], [34.3, 10.1], [33.88, 10.12], [33.65, 11.0], [33.2, 11.25],
  [33.15, 11.55], [32.4, 10.9], [32.1, 10.45], [31.7, 9.9], [30.95, 9.65],
  [30.23, 9.52], [30.3, 9.1], [31.5, 8.35], [32.5, 8.1], [33.2, 8.15],
  [33.85, 7.75], [34.2, 7.5], [34.65, 8.25], [35.25, 8.3], [35.75, 8.25],
  [36.45, 8.2], [36.85, 8.35],
];

// Cadre large : tout ce qui est hors Tunisie est attenue.
const MASK_FRAME: [number, number][] = [
  [20, -5], [20, 25], [45, 25], [45, -5],
];

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
  // Custom Div Icon Creator
  const createCustomIcon = (totalExams: number, interprete: number, name: string, isSelected: boolean) => {
    const siteAverage = totalExams / 3;
    const isAboveAverage = interprete > siteAverage;
    // Un site sans aucun examen est neutre, pas "sous moyenne" : sinon un site
    // simplement silencieux est signale comme un site en difficulte.
    const colorClass = totalExams === 0
      ? "bg-slate-400"
      : isAboveAverage
        ? "bg-emerald-500"
        : "bg-red-500";
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
      bounds={[
        [30.15, 7.45],
        [37.55, 11.65],
      ]}
      boundsOptions={{ padding: [24, 24] }}
      minZoom={6}
      maxZoom={18}
      zoomSnap={0.5}
      zoomControl={true}
      attributionControl={false}
      maxBounds={[
        [29.6, 6.4], // Limite Sud-Ouest
        [38.1, 12.6], // Limite Nord-Est
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
          .leaflet-tile-pane {
              filter: saturate(0.55) brightness(1.03) contrast(0.96);
          }
        `}
      </style>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://www.openstreetmap.fr/">OSM France</a>'
        url="https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png"
        subdomains={["a", "b", "c"]}
        maxZoom={19}
      />

      {/* Masque de focus : le cadre est perce d'un trou en forme de Tunisie. */}
      <Polygon
        positions={[MASK_FRAME, TUNISIA_OUTLINE]}
        pathOptions={{
          fillColor: "#e2e8f0",
          fillOpacity: 0.78,
          stroke: false,
          interactive: false,
        }}
      />
      {/* Lisere du territoire. */}
      <Polygon
        positions={TUNISIA_OUTLINE}
        pathOptions={{
          color: "#1e40af",
          weight: 1.4,
          opacity: 0.55,
          fill: false,
          interactive: false,
        }}
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
                    {totalExams === 0 ? (
                      <div className="mt-1 text-xs font-medium text-slate-500">
                        Aucun examen sur la période sélectionnée
                      </div>
                    ) : (
                      <div
                        className={`mt-1 text-xs font-medium ${
                          isAboveAverage ? "text-emerald-600" : "text-red-600"
                        }`}
                      >
                        {region.interprete} interprétés / moyenne du site : {siteAverage.toFixed(1)}
                      </div>
                    )}
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
