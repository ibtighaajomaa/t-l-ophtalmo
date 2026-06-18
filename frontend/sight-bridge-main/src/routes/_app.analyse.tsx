import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect, useMemo } from "react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Calendar } from "lucide-react";
import { useAuth } from "@/lib/auth-context";

export const Route = createFileRoute("/_app/analyse")({
  component: () => (
    <ProtectedRoute roles={["Admin", "Chef", "Medecin", "Resident"]}>
      <AnalysePage />
    </ProtectedRoute>
  ),
});

export interface RegionData {
  id: string;
  name: string;
  governorate: string;
  lat: number;
  lng: number;
  en_attente: number;
  en_cours: number;
  interprete: number;
}

const REGIONS: RegionData[] = [
  { id: "ghomrassen", name: "Ghomrassen", governorate: "Tataouine", lat: 33.066, lng: 10.333, en_attente: 10, en_cours: 5, interprete: 65 },
  { id: "eljem", name: "El Jem", governorate: "Mahdia", lat: 35.29, lng: 10.71, en_attente: 15, en_cours: 10, interprete: 70 },
  { id: "degache", name: "Degache", governorate: "Tozeur", lat: 33.98, lng: 8.21, en_attente: 12, en_cours: 8, interprete: 60 },
  { id: "souklahad", name: "Souk Lahad", governorate: "Kebili", lat: 33.76, lng: 8.78, en_attente: 5, en_cours: 2, interprete: 22 },
  { id: "regueb", name: "Regueb", governorate: "Sidi Bouzid", lat: 34.86, lng: 9.78, en_attente: 8, en_cours: 4, interprete: 44 },
  { id: "meknassi", name: "Meknassi", governorate: "Sidi Bouzid", lat: 34.61, lng: 9.61, en_attente: 3, en_cours: 1, interprete: 19 },
  { id: "mateur", name: "Mateur", governorate: "Bizerte", lat: 37.04, lng: 9.66, en_attente: 20, en_cours: 15, interprete: 85 },
  { id: "gaafour", name: "Gaâfour", governorate: "Siliana", lat: 36.32, lng: 9.32, en_attente: 6, en_cours: 3, interprete: 28 },
  { id: "kelibia", name: "Kelibia", governorate: "Nabeul", lat: 36.84, lng: 11.09, en_attente: 25, en_cours: 20, interprete: 90 },
  { id: "menzeltemim", name: "Menzel Temim", governorate: "Nabeul", lat: 36.78, lng: 10.98, en_attente: 18, en_cours: 12, interprete: 55 },
];

function AnalysePage() {
  const { user } = useAuth();
  const [period, setPeriod] = useState<"Date" | "Jour" | "Semaine" | "Mois">("Date");
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(null);
  const [filterDate, setFilterDate] = useState<string>("");

  const regionsData = useMemo(() => {
    if (["Chef", "Medecin", "Resident"].includes(user?.role ?? "")) {
      return REGIONS.map((r) => ({
        ...r,
        en_attente: Math.floor(r.en_attente * 0.3),
        en_cours: Math.floor(r.en_cours * 0.3),
        interprete: Math.floor(r.interprete * 0.3),
      }));
    }
    return REGIONS;
  }, [user]);

  // Lazy load MapView to prevent SSR errors with Leaflet
  const [MapViewComponent, setMapViewComponent] = useState<any>(null);

  useEffect(() => {
    import("@/components/MapView").then((mod) => {
      setMapViewComponent(() => mod.default);
    });
  }, []);

  // Compute totals
  const totalInterprete = regionsData.reduce((sum, r) => sum + r.interprete, 0);
  const totalAttente = regionsData.reduce((sum, r) => sum + r.en_attente, 0);
  const totalCours = regionsData.reduce((sum, r) => sum + r.en_cours, 0);
  const averageInterprete = totalInterprete / regionsData.length;

  const totalExams = totalAttente + totalCours + totalInterprete;

  // Selected Data
  const selectedRegion = regionsData.find((r) => r.id === selectedRegionId);
  const displayAttente = selectedRegion ? selectedRegion.en_attente : totalAttente;
  const displayCours = selectedRegion ? selectedRegion.en_cours : totalCours;
  const displayInterprete = selectedRegion ? selectedRegion.interprete : totalInterprete;
  const displayTotal = displayAttente + displayCours + displayInterprete;

  // Progress Bar Widths
  const attenteWidth = (displayAttente / displayTotal) * 100;
  const coursWidth = (displayCours / displayTotal) * 100;
  const interpreteWidth = (displayInterprete / displayTotal) * 100;

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 overflow-auto">
      {/* Header Bar */}
      <header className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6 py-4 shadow-sm">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <Calendar className="h-5 w-5 text-slate-500" />
            <span className="text-sm font-semibold text-slate-700">Période :</span>
            <div className="flex rounded-lg bg-slate-100 p-1">
              {["Date", "Jour", "Semaine", "Mois"].map((p) => (
                <button
                  key={p}
                  onClick={() => setPeriod(p as any)}
                  className={`rounded-md px-3 py-1 text-sm font-medium transition-colors ${period === p
                    ? "bg-white text-blue-600 shadow-sm"
                    : "text-slate-600 hover:text-slate-900"
                    }`}
                >
                  {p}
                </button>
              ))}
            </div>
            {period === "Date" && (
              <input
                type="date"
                value={filterDate}
                onChange={(e) => setFilterDate(e.target.value)}
                className="ml-2 rounded-md border border-slate-200 px-3 py-1 text-sm text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            )}
          </div>
          <div className="hidden sm:flex items-center gap-4 text-sm">
            <div className="flex items-center gap-1.5">
              <span className="h-3 w-3 rounded-full bg-green-500"></span>
              <span className="text-slate-600">Au-dessus de la moyenne (&gt; {averageInterprete.toFixed(1)})</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="h-3 w-3 rounded-full bg-red-500"></span>
              <span className="text-slate-600">En dessous de la moyenne</span>
            </div>
          </div>
        </div>
        <div className="text-sm text-slate-500 italic hidden md:block">
          Cliquez sur un cercle pour filtrer (cliquez à côté pour réinitialiser)
        </div>
      </header>

      {/* Main Content */}
      <div className="flex flex-1 p-6 gap-6 justify-center items-start">
        {/* Left: Interactive Map (Portrait format) */}
        <div
          className="w-[300px] h-[600px] shrink-0 rounded-[16px] border border-black/5 bg-white shadow-[0_10px_30px_rgba(0,0,0,0.08)] overflow-hidden relative z-0"
        >
          {MapViewComponent ? (
            <MapViewComponent
              regions={regionsData}
              selectedRegionId={selectedRegionId}
              setSelectedRegionId={setSelectedRegionId}
              averageInterprete={averageInterprete}
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center bg-slate-50 text-slate-500">
              Chargement de la carte...
            </div>
          )}
        </div>

        {/* Right Sidebar */}
        <div className="w-80 shrink-0 flex flex-col gap-6 overflow-y-auto pr-1 pb-1">
          {/* Summary Card / Histogram */}
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">
              CE {period.toUpperCase()}
            </div>
            <div className="flex items-center gap-2 mb-2">
              <span className={`flex h-6 w-6 items-center justify-center rounded-full ${selectedRegion ? 'bg-indigo-100 text-indigo-600' : 'bg-blue-100 text-blue-600'}`}>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              </span>
              <h2 className="text-lg font-bold text-slate-900">
                {selectedRegion ? `${selectedRegion.name}` : 'Tunisie — Total'}
              </h2>
            </div>
            <p className="text-sm text-slate-500 mb-6">{displayTotal} examens - Ce {period.toLowerCase()}</p>

            {/* Progress Bars (Histogram) */}
            <div className="space-y-4">
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="flex items-center gap-1.5 text-orange-600 font-medium">
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    En attente
                  </span>
                  <span className="font-semibold text-slate-900">{displayAttente}</span>
                </div>
                <div className="h-4 w-full rounded-full bg-orange-50 overflow-hidden">
                  <div className="h-full bg-orange-500 rounded-full transition-all duration-500" style={{ width: `${attenteWidth}%` }}></div>
                </div>
              </div>

              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="flex items-center gap-1.5 text-blue-600 font-medium">
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    En cours
                  </span>
                  <span className="font-semibold text-slate-900">{displayCours}</span>
                </div>
                <div className="h-4 w-full rounded-full bg-blue-50 overflow-hidden">
                  <div className="h-full bg-blue-500 rounded-full transition-all duration-500" style={{ width: `${coursWidth}%` }}></div>
                </div>
              </div>

              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="flex items-center gap-1.5 text-green-600 font-medium">
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    Interprété
                  </span>
                  <span className="font-semibold text-slate-900">{displayInterprete}</span>
                </div>
                <div className="h-4 w-full rounded-full bg-green-50 overflow-hidden">
                  <div className="h-full bg-green-500 rounded-full transition-all duration-500" style={{ width: `${interpreteWidth}%` }}></div>
                </div>
              </div>
            </div>
            {selectedRegion && (
              <button
                onClick={() => setSelectedRegionId(null)}
                className="mt-6 w-full py-2 text-sm text-slate-500 bg-slate-50 hover:bg-slate-100 rounded-lg transition-colors font-medium border border-slate-200"
              >
                Retour au total national
              </button>
            )}
          </div>

          {/* Regions List */}
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm flex-1 overflow-hidden flex flex-col">
            <h3 className="font-semibold text-slate-900 mb-4">Régions ({regionsData.length})</h3>
            <div className="flex-1 overflow-y-auto pr-2 space-y-1">
              {regionsData.map((region) => {
                const isSelected = selectedRegionId === region.id;
                const isAboveAverage = region.interprete > averageInterprete;
                return (
                  <div
                    key={region.id}
                    onClick={() => setSelectedRegionId(region.id)}
                    className={`flex items-center justify-between py-2.5 border-b border-slate-50 last:border-0 rounded-lg px-2 transition-colors cursor-pointer ${isSelected ? 'bg-blue-50' : 'hover:bg-slate-50'
                      }`}
                  >
                    <div className="flex items-center gap-3">
                      <span className={`h-2.5 w-2.5 rounded-full ${isAboveAverage ? 'bg-green-500' : 'bg-red-500'} ${isSelected ? 'ring-2 ring-offset-1 ring-red-300' : ''}`}></span>
                      <div className="flex flex-col">
                        <span className={`text-sm ${isSelected ? 'font-bold text-blue-700' : 'font-medium text-slate-700'}`}>{region.name}</span>
                        <span className="text-[10px] text-slate-400">{region.governorate}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <span className={`text-sm ${isSelected ? 'font-bold text-blue-700' : 'font-semibold text-slate-900'}`}>{region.interprete}</span>
                      <svg className={`w-3 h-3 ${isSelected ? 'text-blue-500' : 'text-slate-400'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
