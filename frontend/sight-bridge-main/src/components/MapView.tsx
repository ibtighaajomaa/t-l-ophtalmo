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
  averageInterprete,
}: {
  regions: RegionData[];
  selectedRegionId: string | null;
  setSelectedRegionId: (id: string | null) => void;
  averageInterprete: number;
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
  const createCustomIcon = (interprete: number, name: string, isSelected: boolean) => {
    const isAboveAverage = interprete > averageInterprete;
    const colorClass = isAboveAverage ? "bg-green-500" : "bg-red-500";
    const borderClass = isSelected
      ? "border-[3px] border-white shadow-[0_4px_12px_rgba(0,0,0,0.3)] scale-110"
      : "border-2 border-white shadow-[0_3px_6px_rgba(0,0,0,0.16)]";

    return L.divIcon({
      html: `
        <div class="relative flex flex-col items-center justify-center -mt-4">
          <div class="w-[35px] h-[35px] rounded-full ${colorClass} ${borderClass} opacity-95 hover:opacity-100 transition-all flex items-center justify-center text-white font-bold text-[14px]" style="font-family: 'Helvetica Neue', Arial, sans-serif;">
            ${interprete}
          </div>
          <div class="bg-white/95 px-2 py-0.5 mt-1 rounded text-xs font-bold text-slate-800 shadow-sm whitespace-nowrap border border-slate-100">
            ${name}
          </div>
        </div>
      `,
      className: "",
      iconSize: [45, 60],
      iconAnchor: [22.5, 30],
    });
  };

  return (
    <MapContainer
      center={[34.0, 9.5]}
      zoom={6.5}
      minZoom={6}
      maxZoom={18}
      zoomSnap={0.5}
      zoomControl={true}
      attributionControl={false}
      maxBounds={[
        [29.5, 6.0], // Limite Sud-Ouest
        [38.0, 13.0], // Limite Nord-Est
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
              box-shadow: 0 4px 12px rgba(0,0,0,0.1) !important;
          }
          .leaflet-bar a {
              background-color: #ffffff !important;
              color: #333333 !important;
              border-bottom: 1px solid #f4f4f4 !important;
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
          return L.divIcon({
            html: `
              <div class="w-[45px] h-[45px] rounded-full bg-blue-500/20 flex items-center justify-center">
                <div class="w-[35px] h-[35px] bg-slate-800 text-white font-bold text-[14px] rounded-full flex items-center justify-center shadow-[0_3px_6px_rgba(0,0,0,0.16)]" style="font-family: 'Helvetica Neue', Arial, sans-serif;">
                  ${cluster.getChildCount()}
                </div>
              </div>
            `,
            className: "",
            iconSize: [45, 45],
          });
        }}
      >
        {regions.map((region) => (
          <Marker
            key={region.id}
            position={[region.lat, region.lng]}
            icon={createCustomIcon(region.interprete, region.name, selectedRegionId === region.id)}
            eventHandlers={{
              click: () => {
                setSelectedRegionId(region.id === selectedRegionId ? null : region.id);
              },
            }}
          >
            <Popup>
              <div className="text-center">
                <strong className="block text-sm">{region.name}</strong>
                <span className="text-xs text-slate-500">{region.governorate}</span>
              </div>
            </Popup>
          </Marker>
        ))}
      </MarkerClusterGroup>
    </MapContainer>
  );
}
