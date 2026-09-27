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
  [37.3658, 9.7462], [37.3483, 9.6515], [37.3123, 9.5828], [37.321, 9.5457], [37.2817, 9.4647],
  [37.2926, 9.4331], [37.2325, 9.2436], [37.2555, 9.223], [37.2467, 9.1873], [37.1899, 9.142],
  [37.1669, 9.0555], [37.1395, 8.9964], [37.0782, 8.9456], [36.9883, 8.822], [36.974, 8.7726],
  [36.9861, 8.7369], [36.9478, 8.6406], [36.9137, 8.6517], [36.9027, 8.6353], [36.8533, 8.6256],
  [36.8533, 8.6545], [36.8313, 8.6847], [36.8148, 8.6723], [36.7917, 8.6133], [36.7972, 8.6009],
  [36.7741, 8.5735], [36.7719, 8.5501], [36.7829, 8.5226], [36.7774, 8.4746], [36.7587, 8.4334],
  [36.7477, 8.432], [36.7532, 8.4554], [36.7455, 8.4636], [36.6949, 8.4869], [36.6662, 8.4691],
  [36.6585, 8.4512], [36.6177, 8.4499], [36.6199, 8.4183], [36.61, 8.3894], [36.5946, 8.3839],
  [36.5747, 8.3276], [36.5538, 8.3153], [36.524, 8.2246], [36.5074, 8.2013], [36.5118, 8.1793],
  [36.4942, 8.1546], [36.4655, 8.1683], [36.4633, 8.1931], [36.4489, 8.2054], [36.439, 8.2672],
  [36.4368, 8.3496], [36.4445, 8.3551], [36.4235, 8.3771], [36.4224, 8.4087], [36.4003, 8.3977],
  [36.3826, 8.4032], [36.3538, 8.3949], [36.3494, 8.3771], [36.3074, 8.3867], [36.2952, 8.3606],
  [36.2675, 8.3386], [36.2553, 8.3524], [36.2232, 8.3537], [36.1711, 8.3112], [36.1368, 8.3386],
  [36.0891, 8.3455], [36.078, 8.3194], [36.0447, 8.2947], [35.958, 8.2892], [35.9157, 8.2576],
  [35.9046, 8.2672], [35.8846, 8.2562], [35.8623, 8.2741], [35.7387, 8.2631], [35.7164, 8.2741],
  [35.6751, 8.3441], [35.6473, 8.3578], [35.5546, 8.3565], [35.4875, 8.3716], [35.4674, 8.3853],
  [35.4573, 8.351], [35.4193, 8.3194], [35.4002, 8.3372], [35.3588, 8.3112], [35.3174, 8.3098],
  [35.2882, 8.3263], [35.2423, 8.421], [35.2378, 8.4705], [35.1379, 8.4087], [35.0941, 8.3482],
  [34.9501, 8.3125], [34.922, 8.248], [34.798, 8.2864], [34.7709, 8.2809], [34.7461, 8.2933],
  [34.7348, 8.3194], [34.7281, 8.3002], [34.6908, 8.2631], [34.6886, 8.2411], [34.6761, 8.2411],
  [34.6592, 8.2796], [34.6309, 8.237], [34.6163, 8.2521], [34.6072, 8.2191], [34.588, 8.2068],
  [34.5801, 8.2191], [34.571, 8.1752], [34.5247, 8.1381], [34.5111, 8.0763], [34.4964, 8.0736],
  [34.4884, 8.0392], [34.4579, 8.009], [34.4466, 7.9596], [34.4194, 7.9294], [34.4012, 7.858],
  [34.3559, 7.8525], [34.2481, 7.8127], [34.2129, 7.814], [34.1652, 7.7385], [34.1948, 7.6575],
  [34.1414, 7.6204], [34.1129, 7.6135], [34.072, 7.5339], [34.014, 7.5572], [33.9718, 7.538],
  [33.9342, 7.5394], [33.8966, 7.5201], [33.8351, 7.5449], [33.7974, 7.5284], [33.7746, 7.5641],
  [33.7243, 7.5641], [33.6912, 7.5902], [33.6409, 7.6012], [33.4246, 7.7344], [33.3672, 7.7344],
  [33.3259, 7.7467], [33.3225, 7.7797], [33.1858, 7.8305], [33.1858, 7.9074], [33.0961, 8.1161],
  [33.0501, 8.1161], [32.815, 8.3304], [32.5098, 8.3578], [32.0849, 9.0747], [30.2306, 9.56],
  [30.2533, 9.6323], [30.2787, 9.6672], [30.3224, 9.7767], [30.338, 9.8245], [30.3415, 9.8762],
  [30.379, 9.9324], [30.4444, 9.998], [30.5077, 10.0219], [30.5696, 10.0834],
  [30.6864, 10.1757], [30.7083, 10.2109], [30.8191, 10.2729], [30.9001, 10.2988],
  [31.0389, 10.2712], [31.0825, 10.2832], [31.1147, 10.2605], [31.1805, 10.2534],
  [31.2017, 10.2331], [31.478, 10.1273], [31.5649, 10.2092], [31.6994, 10.3025],
  [31.7408, 10.3849], [31.7299, 10.457], [31.7425, 10.5283], [31.7742, 10.5587],
  [31.8005, 10.5633], [31.8788, 10.6348], [31.9163, 10.6173], [31.9582, 10.6334],
  [31.9807, 10.6599], [31.9688, 10.7204], [31.9885, 10.7454], [31.9994, 10.7913],
  [32.082, 10.8552], [32.104, 10.8586], [32.1788, 10.9789], [32.263, 11.1672],
  [32.3154, 11.3503], [32.4097, 11.5535], [32.4592, 11.6085], [32.5222, 11.604],
  [32.5757, 11.5625], [32.6053, 11.5109], [32.6548, 11.484], [32.7031, 11.4974],
  [32.7691, 11.489], [32.8494, 11.5054], [32.8918, 11.4882], [32.9838, 11.52],
  [33.084, 11.5302], [33.1445, 11.5604], [33.1801, 11.5659], [33.2364, 11.4258],
  [33.3615, 11.1909], [33.4418, 11.1278], [33.4773, 11.147], [33.5586, 11.1346],
  [33.6695, 11.0234], [33.7118, 11.0138], [33.738, 11.055], [33.7963, 11.0797],
  [33.8453, 11.066], [33.8499, 11.0358], [33.9229, 10.9328], [33.9274, 10.8751],
  [33.9069, 10.8531], [33.9229, 10.7913], [33.9069, 10.7295], [33.883, 10.7185],
  [33.8271, 10.724], [33.7746, 10.7117], [33.7392, 10.6815], [33.7061, 10.6485],
  [33.6832, 10.5771], [33.6764, 10.5098], [33.7301, 10.3423], [33.8636, 10.1706],
  [33.9365, 10.1115], [34.105, 10.0497], [34.2186, 10.0882], [34.2913, 10.1363],
  [34.348, 10.2846], [34.3355, 10.3258], [34.3695, 10.3409], [34.408, 10.3944],
  [34.4522, 10.4329], [34.4896, 10.4919], [34.5077, 10.5812], [34.5428, 10.6238],
  [34.5959, 10.6444], [34.6434, 10.7556], [34.7766, 10.8559], [34.7766, 10.9026],
  [34.824, 10.9053], [34.8983, 10.9492], [34.9512, 10.9465], [35.0165, 11.0495],
  [35.1345, 11.0646], [35.1345, 11.0893], [35.1974, 11.1456], [35.2086, 11.1786],
  [35.2344, 11.18], [35.3633, 11.0495], [35.4036, 11.0811], [35.4405, 11.066],
  [35.511, 11.0852], [35.5479, 11.0591], [35.5859, 11.0591], [35.6439, 11.0783],
  [35.7108, 10.8517], [35.7811, 10.8655], [35.8033, 10.8421], [35.7877, 10.724],
  [35.8289, 10.6691], [35.9936, 10.5482], [36.0424, 10.5304], [36.0624, 10.4961],
  [36.1212, 10.4823], [36.1966, 10.4837], [36.3771, 10.5798], [36.3848, 10.6485],
  [36.4135, 10.7103], [36.4368, 10.8243], [36.5394, 10.871], [36.784, 11.0495],
  [36.8049, 11.1154], [36.8302, 11.147], [36.8774, 11.1539], [36.9148, 11.1195],
  [36.9729, 11.1099], [37.0179, 11.0811], [37.0552, 11.0989], [37.0979, 11.0632],
  [37.1023, 11.0193], [37.0628, 10.9726], [37.0639, 10.9122], [37.0508, 10.8847],
  [37.0234, 10.882], [36.9883, 10.849], [36.962, 10.779], [36.9005, 10.713], [36.9005, 10.6334],
  [36.8785, 10.5675], [36.8313, 10.5496], [36.7708, 10.5441], [36.7246, 10.4192],
  [36.74, 10.3423], [36.7851, 10.312], [36.839, 10.3505], [36.8818, 10.3642],
  [36.8917, 10.3395], [36.9279, 10.3299], [36.9696, 10.2351], [37.0157, 10.2036],
  [37.0596, 10.1981], [37.1384, 10.242], [37.1614, 10.2791], [37.1691, 10.334],
  [37.1899, 10.3381], [37.2238, 10.2036], [37.2828, 10.069], [37.262, 9.9962], [37.262, 9.911],
  [37.3036, 9.8836], [37.3385, 9.8795], [37.3527, 9.852], [37.3483, 9.7861]
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
          /* Pas de filtre global : le masque attenue l'exterieur, le
             territoire doit rester parfaitement lisible. */
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
          fillColor: "#ffffff",
          fillOpacity: 0.7,
          stroke: false,
          interactive: false,
        }}
      />
      {/* Halo : separe le territoire du voisinage reste visible. */}
      <Polygon
        positions={TUNISIA_OUTLINE}
        pathOptions={{
          color: "#ffffff",
          weight: 7,
          opacity: 0.85,
          fill: false,
          interactive: false,
        }}
      />
      {/* Lisere du territoire. */}
      <Polygon
        positions={TUNISIA_OUTLINE}
        pathOptions={{
          color: "#1d4ed8",
          weight: 2,
          opacity: 0.9,
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
