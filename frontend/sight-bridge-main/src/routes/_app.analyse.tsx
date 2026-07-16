import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect, useMemo } from "react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import {
  Activity,
  Calendar,
  CheckCircle2,
  Clock3,
  MapPin,
  Radio,
  RotateCw,
  TrendingUp,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchExams } from "@/lib/exam-api";
import type { Exam } from "@/lib/mock-worklist";

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

type SiteLocation = {
  name: string;
  governorate: string;
  lat: number;
  lng: number;
};

const SITE_LOCATIONS: Record<string, SiteLocation> = {
  kelibia: { name: "Kélibia", governorate: "Nabeul", lat: 36.84, lng: 11.09 },
  "hopital circonscrition kelibia": {
    name: "Kélibia",
    governorate: "Nabeul",
    lat: 36.84,
    lng: 11.09,
  },
  "hopital circonscription kelibia": {
    name: "Kélibia",
    governorate: "Nabeul",
    lat: 36.84,
    lng: 11.09,
  },
  mateur: { name: "Mateur", governorate: "Bizerte", lat: 37.04, lng: 9.66 },
  "manzel temim": { name: "Menzel Temim", governorate: "Nabeul", lat: 36.78, lng: 10.98 },
  "menzel temim": { name: "Menzel Temim", governorate: "Nabeul", lat: 36.78, lng: 10.98 },
  kebili: { name: "Kébili", governorate: "Kébili", lat: 33.705, lng: 8.969 },
  deguech: { name: "Deguech", governorate: "Tozeur", lat: 33.98, lng: 8.21 },
  siliana: { name: "Siliana", governorate: "Siliana", lat: 36.08, lng: 9.37 },
  "el fahes": { name: "El Fahes", governorate: "Zaghouan", lat: 36.37, lng: 9.91 },
  gaafour: { name: "Gaâfour", governorate: "Siliana", lat: 36.32, lng: 9.32 },
  ghomrassen: { name: "Ghomrassen", governorate: "Tataouine", lat: 33.066, lng: 10.333 },
  "el jem": { name: "El Jem", governorate: "Mahdia", lat: 35.29, lng: 10.71 },
  "souk lahad": { name: "Souk Lahad", governorate: "Kébili", lat: 33.76, lng: 8.78 },
  regueb: { name: "Regueb", governorate: "Sidi Bouzid", lat: 34.86, lng: 9.78 },
  meknassi: { name: "Meknassi", governorate: "Sidi Bouzid", lat: 34.61, lng: 9.61 },
  "etablissement inconnu": {
    name: "Établissement inconnu",
    governorate: "Non cartographié",
    lat: 34.0,
    lng: 9.5,
  },
};

const STATUS_COLORS = {
  attente: "#ff832b",
  cours: "#0f62fe",
  interprete: "#24a148",
};

function formatNumber(value: number) {
  return new Intl.NumberFormat("fr-FR").format(value);
}

function percentage(value: number, total: number) {
  if (!total) return 0;
  return Math.round((value / total) * 100);
}

function normalizeSiteName(value?: string) {
  return (value || "Établissement inconnu")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^\w\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function canonicalSite(exam: Exam) {
  const rawName = exam.institutionName || exam.region || "Établissement inconnu";
  const key = normalizeSiteName(rawName);
  const location = SITE_LOCATIONS[key];
  if (location) return { id: key, ...location };

  return {
    id: key || "etablissement-inconnu",
    name: rawName,
    governorate: "Site à géolocaliser",
    lat: 34.0,
    lng: 9.5,
  };
}

function parseLocalDate(value: string) {
  return new Date(`${value}T00:00:00`);
}

function dateKey(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isExamInPeriod(exam: Exam, period: "Date" | "Jour" | "Semaine" | "Mois", filterDate: string) {
  if (!exam.date) return false;
  const examDate = parseLocalDate(exam.date);
  const today = new Date();

  if (period === "Date") {
    return filterDate ? exam.date === filterDate : true;
  }

  if (period === "Jour") {
    return exam.date === dateKey(today);
  }

  if (period === "Semaine") {
    const start = new Date(today);
    start.setDate(today.getDate() - 6);
    start.setHours(0, 0, 0, 0);
    return examDate >= start && examDate <= today;
  }

  return examDate.getFullYear() === today.getFullYear() && examDate.getMonth() === today.getMonth();
}

function aggregateRegions(exams: Exam[]): RegionData[] {
  const bySite = new Map<string, RegionData>();

  for (const exam of exams) {
    const site = canonicalSite(exam);
    const current =
      bySite.get(site.id) ||
      ({
        id: site.id,
        name: site.name,
        governorate: site.governorate,
        lat: site.lat,
        lng: site.lng,
        en_attente: 0,
        en_cours: 0,
        interprete: 0,
      } satisfies RegionData);

    if (exam.status === "Interprété") {
      current.interprete += 1;
    } else if (exam.status === "En cours") {
      current.en_cours += 1;
    } else {
      current.en_attente += 1;
    }

    bySite.set(site.id, current);
  }

  return [...bySite.values()].sort(
    (a, b) =>
      b.en_attente +
      b.en_cours +
      b.interprete -
      (a.en_attente + a.en_cours + a.interprete),
  );
}

function KpiTile({
  label,
  value,
  detail,
  icon: Icon,
  tone,
}: {
  label: string;
  value: number | string;
  detail: string;
  icon: typeof Activity;
  tone: "blue" | "green" | "orange" | "slate";
}) {
  const toneClasses = {
    blue: "text-blue-700 bg-blue-50 ring-blue-100",
    green: "text-emerald-700 bg-emerald-50 ring-emerald-100",
    orange: "text-orange-700 bg-orange-50 ring-orange-100",
    slate: "text-slate-700 bg-slate-50 ring-slate-100",
  };

  return (
    <div className="border-r border-slate-200 px-5 py-4 last:border-r-0">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
          <div className="mt-2 text-2xl font-semibold tabular-nums text-slate-950">{value}</div>
          <div className="mt-1 text-xs text-slate-500">{detail}</div>
        </div>
        <span className={`rounded-md p-2 ring-1 ${toneClasses[tone]}`}>
          <Icon className="h-4 w-4" />
        </span>
      </div>
    </div>
  );
}

function AnalysePage() {
  const [period, setPeriod] = useState<"Date" | "Jour" | "Semaine" | "Mois">("Date");
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(null);
  const [filterDate, setFilterDate] = useState<string>("");
  const [exams, setExams] = useState<Exam[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadCurrentExams() {
      setLoading(true);
      setError(null);
      try {
        const result = await fetchExams({ page_size: 10000 });
        if (!cancelled) setExams(result.exams);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Impossible de charger les données");
          setExams([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadCurrentExams();
    return () => {
      cancelled = true;
    };
  }, []);

  const scopedExams = useMemo(
    () => exams.filter((exam) => isExamInPeriod(exam, period, filterDate)),
    [exams, period, filterDate],
  );

  const regionsData = useMemo(() => aggregateRegions(scopedExams), [scopedExams]);

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

  const totalExams = totalAttente + totalCours + totalInterprete;

  // Selected Data
  const selectedRegion = regionsData.find((r) => r.id === selectedRegionId);
  const displayAttente = selectedRegion ? selectedRegion.en_attente : totalAttente;
  const displayCours = selectedRegion ? selectedRegion.en_cours : totalCours;
  const displayInterprete = selectedRegion ? selectedRegion.interprete : totalInterprete;
  const displayTotal = displayAttente + displayCours + displayInterprete;

  const completionRate = percentage(totalInterprete, totalExams);
  const pendingRate = percentage(totalAttente, totalExams);
  const activeSites = regionsData.length;
  const belowAverage = regionsData.filter((region) => {
    const regionTotal = region.en_attente + region.en_cours + region.interprete;
    const regionAverage = regionTotal / 3;
    return region.interprete <= regionAverage;
  }).length;

  const trendData = useMemo(() => {
    const grouped = new Map<string, { label: string; examens: number; interpretes: number }>();
    const source = period === "Date" && !filterDate ? exams : scopedExams;

    for (const exam of source) {
      if (!exam.date) continue;
      const current = grouped.get(exam.date) || {
        label: exam.date.slice(5),
        examens: 0,
        interpretes: 0,
      };
      current.examens += 1;
      if (exam.status === "Interprété") current.interpretes += 1;
      grouped.set(exam.date, current);
    }

    return [...grouped.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .slice(-8)
      .map(([, value]) => value);
  }, [exams, scopedExams, period, filterDate]);

  const statusBars = [
    { name: "En attente", value: displayAttente, color: STATUS_COLORS.attente },
    { name: "En cours", value: displayCours, color: STATUS_COLORS.cours },
    { name: "Interprété", value: displayInterprete, color: STATUS_COLORS.interprete },
  ];

  const rankedRegions = useMemo(
    () => [...regionsData].sort((a, b) => b.interprete - a.interprete),
    [regionsData],
  );

  return (
    <div className="min-h-screen overflow-auto bg-[#f4f6f8] text-slate-950">
      <div className="border-b border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-4 px-6 py-4">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-blue-700">
              <Radio className="h-4 w-4" />
              Projet national pilote
            </div>
            <h1 className="mt-1 text-xl font-semibold text-slate-950">
              Supervision de la télé-rétinographie
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              Couverture, interprétation et files actives par établissement.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center rounded-lg border border-slate-200 bg-slate-50 p-1">
              {["Date", "Jour", "Semaine", "Mois"].map((p) => (
                <button
                  key={p}
                  onClick={() => setPeriod(p as typeof period)}
                  className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                    period === p
                      ? "bg-white text-blue-700 shadow-sm ring-1 ring-slate-200"
                      : "text-slate-600 hover:text-slate-950"
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
            {period === "Date" && (
              <label className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600">
                <Calendar className="h-4 w-4 text-slate-500" />
                <input
                  type="date"
                  value={filterDate}
                  onChange={(event) => setFilterDate(event.target.value)}
                  className="bg-transparent text-slate-700 outline-none"
                />
              </label>
            )}
          </div>
        </div>

        <div className="grid border-t border-slate-200 bg-white sm:grid-cols-2 xl:grid-cols-4">
          <KpiTile
            label="Examens collectés"
            value={formatNumber(totalExams)}
            detail={`${activeSites} sites pilotes actifs`}
            icon={Activity}
            tone="blue"
          />
          <KpiTile
            label="Taux interprété"
            value={`${completionRate}%`}
            detail={`${formatNumber(totalInterprete)} comptes rendus finalisés`}
            icon={CheckCircle2}
            tone="green"
          />
          <KpiTile
            label="File d'attente"
            value={formatNumber(totalAttente)}
            detail={`${pendingRate}% du flux national`}
            icon={Clock3}
            tone="orange"
          />
          <KpiTile
            label="Sites sous moyenne locale"
            value={belowAverage}
            detail="Moyenne site = total / 3 statuts"
            icon={TrendingUp}
            tone="slate"
          />
        </div>
      </div>

      <div className="grid gap-5 p-5 xl:grid-cols-[minmax(0,1fr)_400px]">
        <main className="space-y-5">
          <section className="flex h-[620px] flex-col overflow-hidden rounded-lg border border-slate-200 bg-white">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
              <div>
                <h2 className="text-base font-semibold text-slate-950">Carte nationale des sites</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Nombre total d’examens selon le filtre ; couleur selon les interprétés comparés à la moyenne du site.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
                  Au-dessus moyenne
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-full bg-red-500" />
                  Sous moyenne
                </span>
              </div>
            </div>
            {(loading || error) && (
              <div
                className={`border-b px-5 py-3 text-sm ${
                  error
                    ? "border-red-100 bg-red-50 text-red-700"
                    : "border-blue-100 bg-blue-50 text-blue-700"
                }`}
              >
                {error || "Chargement des données actuelles depuis la worklist..."}
              </div>
            )}
            <div className="min-h-0 flex-1">
              {MapViewComponent && regionsData.length ? (
                <MapViewComponent
                  regions={regionsData}
                  selectedRegionId={selectedRegionId}
                  setSelectedRegionId={setSelectedRegionId}
                />
              ) : !loading && !regionsData.length ? (
                <div className="flex h-full items-center justify-center bg-slate-50 text-sm text-slate-500">
                  Aucune donnée d’examen disponible pour cette période.
                </div>
              ) : (
                <div className="flex h-full items-center justify-center bg-slate-50 text-sm text-slate-500">
                  Chargement de la carte...
                </div>
              )}
            </div>
          </section>

          <section className="rounded-lg border border-slate-200 bg-white">
            <div className="border-b border-slate-200 px-5 py-4">
              <h2 className="text-base font-semibold text-slate-950">Courbe nationale</h2>
              <p className="mt-1 text-sm text-slate-500">Tendance synthétique du flux pilote.</p>
            </div>
            <div className="h-64 px-5 py-4">
              {trendData.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={trendData} margin={{ top: 8, right: 14, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="examensGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#0f62fe" stopOpacity={0.22} />
                        <stop offset="95%" stopColor="#0f62fe" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid vertical={false} stroke="#e2e8f0" />
                    <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#64748b" }} />
                    <YAxis hide />
                    <Tooltip contentStyle={{ borderRadius: 8, borderColor: "#cbd5e1" }} />
                    <Area
                      type="monotone"
                      dataKey="examens"
                      stroke="#0f62fe"
                      strokeWidth={2}
                      fill="url(#examensGradient)"
                      name="Examens"
                    />
                    <Area
                      type="monotone"
                      dataKey="interpretes"
                      stroke="#24a148"
                      strokeWidth={2}
                      fill="transparent"
                      name="Interprétés"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-slate-500">
                  Pas assez de données datées pour tracer une courbe.
                </div>
              )}
            </div>
          </section>
        </main>

        <aside className="space-y-5">
          <section className="flex h-[620px] flex-col overflow-hidden rounded-lg border border-slate-200 bg-white">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <h2 className="text-base font-semibold text-slate-950">Établissements pilotes</h2>
              <span className="text-xs text-slate-500">{regionsData.length} sites</span>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {rankedRegions.map((region, index) => {
                const isSelected = selectedRegionId === region.id;
                const regionTotal = region.en_attente + region.en_cours + region.interprete;
                const regionAverage = regionTotal / 3;
                const isAboveAverage = region.interprete > regionAverage;
                return (
                  <button
                    key={region.id}
                    onClick={() => setSelectedRegionId(region.id)}
                    className={`grid w-full grid-cols-[32px_minmax(0,1fr)_auto] items-center gap-3 border-b border-slate-100 px-5 py-3 text-left transition last:border-b-0 ${
                      isSelected ? "bg-blue-50" : "hover:bg-slate-50"
                    }`}
                  >
                    <span className="text-xs font-semibold tabular-nums text-slate-400">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span className="min-w-0">
                      <span className="flex items-center gap-2">
                        <span
                          className={`h-2 w-2 rounded-full ${isAboveAverage ? "bg-emerald-500" : "bg-red-500"}`}
                        />
                        <span className="truncate text-sm font-semibold text-slate-800">{region.name}</span>
                      </span>
                      <span className="mt-0.5 block text-xs text-slate-500">
                        {region.governorate} · {formatNumber(regionTotal)} examens
                      </span>
                    </span>
                    <span className="text-right">
                      <span className="block text-sm font-semibold tabular-nums text-slate-950">
                        {formatNumber(regionTotal)}
                      </span>
                      <span className="block text-[11px] text-slate-500">
                        {formatNumber(region.interprete)} interpr.
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="rounded-lg border border-slate-200 bg-white">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {selectedRegion ? selectedRegion.governorate : "National"}
                </div>
                <h2 className="mt-1 flex items-center gap-2 text-base font-semibold text-slate-950">
                  <MapPin className="h-4 w-4 text-blue-700" />
                  {selectedRegion ? selectedRegion.name : "Tunisie — consolidation"}
                </h2>
              </div>
              {selectedRegion && (
                <button
                  onClick={() => setSelectedRegionId(null)}
                  className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
                >
                  <RotateCw className="h-3.5 w-3.5" />
                  National
                </button>
              )}
            </div>

            <div className="grid grid-cols-3 divide-x divide-slate-200 border-b border-slate-200">
              {statusBars.map((item) => (
                <div key={item.name} className="px-4 py-3">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                    {item.name}
                  </div>
                  <div className="mt-1 text-lg font-semibold tabular-nums text-slate-950">
                    {formatNumber(item.value)}
                  </div>
                </div>
              ))}
            </div>

            <div className="px-5 py-4">
              <div className="mb-3 flex items-center justify-between text-sm">
                <span className="font-medium text-slate-700">Répartition du flux</span>
                <span className="tabular-nums text-slate-500">{formatNumber(displayTotal)} examens</span>
              </div>
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={statusBars} layout="vertical" margin={{ top: 4, right: 12, left: 4, bottom: 4 }}>
                    <CartesianGrid horizontal={false} stroke="#e2e8f0" />
                    <XAxis type="number" hide domain={[0, "dataMax"]} />
                    <YAxis
                      type="category"
                      dataKey="name"
                      width={76}
                      tickLine={false}
                      axisLine={false}
                      tick={{ fontSize: 12, fill: "#475569" }}
                    />
                    <Tooltip
                      cursor={{ fill: "#f8fafc" }}
                      contentStyle={{ borderRadius: 8, borderColor: "#cbd5e1" }}
                    />
                    <Bar dataKey="value" radius={[0, 6, 6, 0]} barSize={18}>
                      {statusBars.map((entry) => (
                        <Cell key={entry.name} fill={entry.color} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </section>

        </aside>
      </div>
    </div>
  );
}
