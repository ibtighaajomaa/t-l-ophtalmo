import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect, useMemo } from "react";
import type { ComponentType } from "react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import {
  Activity,
  Calendar,
  CheckCircle2,
  Clock3,
  MapPin,
  Radio,
  RotateCw,
  Stethoscope,
  TrendingUp,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchAllExams, fetchPlatformDoctors } from "@/lib/exam-api";
import type { PlatformDoctor } from "@/lib/exam-api";
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

type MapViewProps = {
  regions: RegionData[];
  selectedRegionId: string | null;
  setSelectedRegionId: (id: string | null) => void;
};

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
  attenteAujourdhui: "#8a3ffc",
  retraitAccumule: "#da1e28",
  nonAssigneAccumule: "#f1c21b",
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

function normalizeDoctorName(value?: string | null) {
  return (value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/^(dr\.?|pr\.?)\s+/i, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function isAssignedToDoctor(exam: Exam, doctorName: string) {
  return normalizeDoctorName(exam.assignedTo) === normalizeDoctorName(doctorName);
}

function isRemovedFromDoctor(exam: Exam, doctorName?: string) {
  if (!exam.isReassigned24h || !exam.reassignedFromName) return false;
  if (!doctorName) return true;
  return normalizeDoctorName(exam.reassignedFromName) === normalizeDoctorName(doctorName);
}

function isWaitingNotAssigned(exam: Exam) {
  return exam.status === "En attente" && !exam.assignedTo;
}

function isWaitingAssignedOrRemoved(exam: Exam, doctorName?: string) {
  return (
    exam.status === "En attente" &&
    (Boolean(exam.assignedTo) || isRemovedFromDoctor(exam, doctorName))
  );
}

function isWaitingVisibleInBreakdown(exam: Exam, doctorName?: string) {
  if (exam.status !== "En attente") return false;
  if (!doctorName) return true;
  return (
    !exam.assignedTo ||
    isAssignedToDoctor(exam, doctorName) ||
    isRemovedFromDoctor(exam, doctorName)
  );
}

function waitingBreakdownKind(exam: Exam, referenceDate: string, doctorName?: string) {
  if (isWaitingAssignedOrRemoved(exam, doctorName)) return "retrait";
  if (isWaitingNotAssigned(exam) && exam.date === referenceDate) return "aujourdhui";
  return "nonAssigneAccumule";
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

type AnalysePeriod = "Date" | "Jour" | "Semaine" | "Mois" | "Année";

function isExamInPeriod(exam: Exam, period: AnalysePeriod, filterDate: string) {
  if (!exam.date) return false;
  const examDate = parseLocalDate(exam.date);
  const today = new Date();

  if (period === "Date") {
    return examDate <= parseLocalDate(filterDate || dateKey(today));
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

  if (period === "Mois") {
    return (
      examDate.getFullYear() === today.getFullYear() && examDate.getMonth() === today.getMonth()
    );
  }

  return examDate.getFullYear() === today.getFullYear();
}

function monthLabel(value: string) {
  return new Intl.DateTimeFormat("fr-FR", { month: "short" }).format(parseLocalDate(`${value}-01`));
}

function buildTrendBucket(examDate: string, period: AnalysePeriod) {
  if (period === "Année") {
    const key = examDate.slice(0, 7);
    return { key, label: monthLabel(key) };
  }

  return { key: examDate, label: examDate.slice(5) };
}

function buildTrendBuckets(period: AnalysePeriod, filterDate: string) {
  const today = new Date();

  if (period === "Année") {
    return Array.from({ length: today.getMonth() + 1 }, (_, index) => {
      const month = String(index + 1).padStart(2, "0");
      const key = `${today.getFullYear()}-${month}`;
      return { key, label: monthLabel(key) };
    });
  }

  if (period === "Mois") {
    const days = today.getDate();
    return Array.from({ length: days }, (_, index) => {
      const date = new Date(today.getFullYear(), today.getMonth(), index + 1);
      const key = dateKey(date);
      return { key, label: key.slice(5) };
    });
  }

  if (period === "Semaine") {
    return Array.from({ length: 7 }, (_, index) => {
      const date = new Date(today);
      date.setDate(today.getDate() - (6 - index));
      const key = dateKey(date);
      return { key, label: key.slice(5) };
    });
  }

  const key = period === "Date" ? filterDate || dateKey(today) : dateKey(today);
  return [{ key, label: key.slice(5) }];
}

function trendBucketForExam(examDate: string, period: AnalysePeriod, filterDate: string) {
  if (period === "Date" || period === "Jour") {
    const todayKey = dateKey(new Date());
    const key = period === "Date" ? filterDate || todayKey : todayKey;
    return { key, label: key.slice(5) };
  }

  return buildTrendBucket(examDate, period);
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
    (a, b) => b.en_attente + b.en_cours + b.interprete - (a.en_attente + a.en_cours + a.interprete),
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
  tone: "blue" | "green" | "orange" | "red" | "slate";
}) {
  const toneClasses = {
    blue: "text-blue-700 bg-blue-50 ring-blue-100",
    green: "text-emerald-700 bg-emerald-50 ring-emerald-100",
    orange: "text-orange-700 bg-orange-50 ring-orange-100",
    red: "text-red-700 bg-red-50 ring-red-100",
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
  const [period, setPeriod] = useState<AnalysePeriod>("Semaine");
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(null);
  const [filterDate, setFilterDate] = useState<string>("");
  const [doctorFilter, setDoctorFilter] = useState<string>("");
  const [doctors, setDoctors] = useState<PlatformDoctor[]>([]);
  const [exams, setExams] = useState<Exam[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadCurrentExams() {
      setLoading(true);
      setError(null);
      try {
        const result = await fetchAllExams();
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

  useEffect(() => {
    let cancelled = false;

    async function loadDoctors() {
      try {
        const result = await fetchPlatformDoctors();
        if (!cancelled) setDoctors(result);
      } catch (err) {
        console.error("Erreur de chargement des médecins", err);
        if (!cancelled) setDoctors([]);
      }
    }

    loadDoctors();
    return () => {
      cancelled = true;
    };
  }, []);

  const periodExams = useMemo(
    () => exams.filter((exam) => isExamInPeriod(exam, period, filterDate)),
    [exams, period, filterDate],
  );

  const currentScopedExams = useMemo(() => {
    if (!doctorFilter) return exams;
    return exams.filter((exam) => isAssignedToDoctor(exam, doctorFilter));
  }, [exams, doctorFilter]);

  const scopedExams = useMemo(() => {
    if (!doctorFilter) return periodExams;
    return periodExams.filter((exam) => isAssignedToDoctor(exam, doctorFilter));
  }, [periodExams, doctorFilter]);

  const waitingBreakdownReferenceDate =
    period === "Date" && filterDate ? filterDate : dateKey(new Date());

  const waitingBreakdownExams = useMemo(
    () =>
      scopedExams.filter((exam) => isWaitingVisibleInBreakdown(exam, doctorFilter || undefined)),
    [scopedExams, doctorFilter],
  );

  const regionsData = useMemo(() => aggregateRegions(currentScopedExams), [currentScopedExams]);

  // Lazy load MapView to prevent SSR errors with Leaflet
  const [MapViewComponent, setMapViewComponent] = useState<ComponentType<MapViewProps> | null>(
    null,
  );

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

  const completionRate = percentage(totalInterprete, totalExams);
  const pendingRate = percentage(totalAttente, totalExams);
  const activeSites = regionsData.length;

  const chartScopedExams = useMemo(() => {
    if (!selectedRegionId) return scopedExams;
    return scopedExams.filter((exam) => canonicalSite(exam).id === selectedRegionId);
  }, [scopedExams, selectedRegionId]);

  const chartRegionsData = useMemo(() => aggregateRegions(chartScopedExams), [chartScopedExams]);
  const chartSelectedRegion = selectedRegionId
    ? chartRegionsData.find((r) => r.id === selectedRegionId)
    : undefined;
  const chartTotalAttente = chartSelectedRegion
    ? chartSelectedRegion.en_attente
    : chartRegionsData.reduce((sum, r) => sum + r.en_attente, 0);
  const chartTotalCours = chartSelectedRegion
    ? chartSelectedRegion.en_cours
    : chartRegionsData.reduce((sum, r) => sum + r.en_cours, 0);
  const chartTotalInterprete = chartSelectedRegion
    ? chartSelectedRegion.interprete
    : chartRegionsData.reduce((sum, r) => sum + r.interprete, 0);

  const chartWaitingBreakdownExams = useMemo(() => {
    if (!selectedRegionId) return waitingBreakdownExams;
    return waitingBreakdownExams.filter((exam) => canonicalSite(exam).id === selectedRegionId);
  }, [waitingBreakdownExams, selectedRegionId]);

  const trendData = useMemo(() => {
    const grouped = new Map<
      string,
      { label: string; attente: number; cours: number; interprete: number }
    >(
      buildTrendBuckets(period, filterDate).map((bucket) => [
        bucket.key,
        { label: bucket.label, attente: 0, cours: 0, interprete: 0 },
      ]),
    );

    for (const exam of chartScopedExams) {
      if (!exam.date) continue;
      const bucket = trendBucketForExam(exam.date, period, filterDate);
      const current = grouped.get(bucket.key) || {
        label: bucket.label,
        attente: 0,
        cours: 0,
        interprete: 0,
      };

      if (exam.status === "Interprété") {
        current.interprete += 1;
      } else if (exam.status === "En cours") {
        current.cours += 1;
      } else {
        current.attente += 1;
      }
      grouped.set(bucket.key, current);
    }

    return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, value]) => value);
  }, [chartScopedExams, period, filterDate]);

  const waitingBreakdownData = useMemo(() => {
    const totals = chartWaitingBreakdownExams.reduce(
      (acc, exam) => {
        const kind = waitingBreakdownKind(
          exam,
          waitingBreakdownReferenceDate,
          doctorFilter || undefined,
        );
        if (kind === "aujourdhui") {
          acc.aujourdhui += 1;
        } else if (kind === "retrait") {
          acc.retrait += 1;
        } else {
          acc.nonAssigneAccumule += 1;
        }
        return acc;
      },
      { aujourdhui: 0, retrait: 0, nonAssigneAccumule: 0 },
    );

    return [
      {
        name: "Aujourd’hui",
        value: totals.aujourdhui,
        color: STATUS_COLORS.attenteAujourdhui,
      },
      {
        name: "Après retrait",
        value: totals.retrait,
        color: STATUS_COLORS.retraitAccumule,
      },
      {
        name: "Non assigné accumulé",
        value: totals.nonAssigneAccumule,
        color: STATUS_COLORS.nonAssigneAccumule,
      },
    ];
  }, [chartWaitingBreakdownExams, doctorFilter, waitingBreakdownReferenceDate]);

  const waitingBreakdownTotal = waitingBreakdownData.reduce((sum, item) => sum + item.value, 0);

  const statusBars = [
    { name: "En attente", value: chartTotalAttente, color: STATUS_COLORS.attente },
    { name: "En cours", value: chartTotalCours, color: STATUS_COLORS.cours },
    { name: "Interprété", value: chartTotalInterprete, color: STATUS_COLORS.interprete },
  ];
  const statusBarsTotal = chartTotalAttente + chartTotalCours + chartTotalInterprete;

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
              {["Date", "Jour", "Semaine", "Mois", "Année"].map((p) => (
                <button
                  key={p}
                  onClick={() => setPeriod(p as AnalysePeriod)}
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
            <label className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600">
              <Stethoscope className="h-4 w-4 text-slate-500" />
              <select
                value={doctorFilter}
                onChange={(event) => {
                  setDoctorFilter(event.target.value);
                  setSelectedRegionId(null);
                }}
                className="min-w-[210px] bg-transparent text-slate-700 outline-none"
              >
                <option value="">Tous les médecins</option>
                {doctors.map((doctor) => (
                  <option key={doctor.id} value={doctor.name}>
                    {doctor.name}
                  </option>
                ))}
              </select>
            </label>
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
            value={
              regionsData.filter(
                (region) =>
                  region.interprete <=
                  (region.en_attente + region.en_cours + region.interprete) / 3,
              ).length
            }
            detail="Moyenne site = total / 3 statuts"
            icon={TrendingUp}
            tone="slate"
          />
        </div>
      </div>

      <div className="grid gap-5 p-5 xl:grid-cols-3">
        <main className="space-y-5">
          <section className="flex h-[620px] flex-col overflow-hidden rounded-lg border border-slate-200 bg-white">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
              <div>
                <h2 className="text-base font-semibold text-slate-950">
                  Carte nationale des sites
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  Nombre total d’examens selon le filtre ; couleur selon les interprétés comparés à
                  la moyenne du site.
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
        </main>

        <aside>
          <section className="flex h-[620px] flex-col overflow-hidden rounded-lg border border-slate-200 bg-white">
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

            <div className="flex min-h-0 flex-1 flex-col px-5 py-4">
              <div className="mb-3 flex items-center justify-between text-sm">
                <span className="font-medium text-slate-700">Répartition du flux</span>
                <span className="tabular-nums text-slate-500">
                  {formatNumber(statusBarsTotal)} examens
                </span>
              </div>
              <div className="min-h-[360px] flex-1">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={statusBars} margin={{ top: 8, right: 12, left: -18, bottom: 8 }}>
                    <CartesianGrid vertical={false} stroke="#e2e8f0" />
                    <XAxis
                      dataKey="name"
                      tickLine={false}
                      axisLine={false}
                      tick={{ fontSize: 12, fill: "#475569" }}
                      interval={0}
                    />
                    <YAxis
                      type="number"
                      tickLine={false}
                      axisLine={false}
                      tick={{ fontSize: 12, fill: "#475569" }}
                      allowDecimals={false}
                    />
                    <Tooltip
                      cursor={{ fill: "#f8fafc" }}
                      contentStyle={{ borderRadius: 8, borderColor: "#cbd5e1" }}
                    />
                    <Bar dataKey="value" radius={[6, 6, 0, 0]} barSize={34}>
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

        <aside>
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
                        <span className="truncate text-sm font-semibold text-slate-800">
                          {region.name}
                        </span>
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
        </aside>

        <section className="flex h-[520px] flex-col overflow-hidden rounded-lg border border-slate-200 bg-white xl:col-span-2">
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
            <div>
              <h2 className="text-base font-semibold text-slate-950">
                {selectedRegion ? `Courbe - ${selectedRegion.name}` : "Courbe nationale"}
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                Volumes réels par statut, par jour ou par mois selon le filtre actif.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: STATUS_COLORS.attente }}
                />
                En attente
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: STATUS_COLORS.cours }}
                />
                En cours
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: STATUS_COLORS.interprete }}
                />
                Interprété
              </span>
            </div>
          </div>
          <div className="grid grid-cols-3 divide-x divide-slate-200 border-b border-slate-200 bg-slate-50/60">
            <div className="px-5 py-3">
              <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                En attente
              </div>
              <div className="mt-1 text-lg font-semibold tabular-nums text-orange-600">
                {formatNumber(chartTotalAttente)}
              </div>
            </div>
            <div className="px-5 py-3">
              <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                En cours
              </div>
              <div className="mt-1 text-lg font-semibold tabular-nums text-blue-600">
                {formatNumber(chartTotalCours)}
              </div>
            </div>
            <div className="px-5 py-3">
              <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                Interprété
              </div>
              <div className="mt-1 text-lg font-semibold tabular-nums text-emerald-600">
                {formatNumber(chartTotalInterprete)}
              </div>
            </div>
          </div>
          <div className="min-h-0 flex-1 px-5 py-5">
            {trendData.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trendData} margin={{ top: 8, right: 18, left: -8, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="#e2e8f0" />
                  <XAxis
                    dataKey="label"
                    tickLine={false}
                    axisLine={false}
                    tick={{ fontSize: 11, fill: "#64748b" }}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    allowDecimals={false}
                    tick={{ fontSize: 11, fill: "#64748b" }}
                  />
                  <Tooltip
                    cursor={{ stroke: "#cbd5e1", strokeDasharray: "4 4" }}
                    contentStyle={{ borderRadius: 8, borderColor: "#cbd5e1" }}
                    formatter={(value: number, name: string) => [formatNumber(Number(value)), name]}
                  />
                  <Line
                    type="monotone"
                    dataKey="attente"
                    stroke={STATUS_COLORS.attente}
                    strokeWidth={2}
                    dot={{ r: 3, strokeWidth: 2, fill: "#ffffff" }}
                    activeDot={{ r: 5 }}
                    name="En attente"
                  />
                  <Line
                    type="monotone"
                    dataKey="cours"
                    stroke={STATUS_COLORS.cours}
                    strokeWidth={2}
                    dot={{ r: 3, strokeWidth: 2, fill: "#ffffff" }}
                    activeDot={{ r: 5 }}
                    name="En cours"
                  />
                  <Line
                    type="monotone"
                    dataKey="interprete"
                    stroke={STATUS_COLORS.interprete}
                    strokeWidth={2}
                    dot={{ r: 3, strokeWidth: 2, fill: "#ffffff" }}
                    activeDot={{ r: 5 }}
                    name="Interprété"
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                Pas assez de données datées pour tracer une courbe.
              </div>
            )}
          </div>
        </section>

        <section className="flex h-[520px] flex-col overflow-hidden rounded-lg border border-slate-200 bg-white">
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
            <div>
              <h2 className="text-base font-semibold text-slate-950">
                {selectedRegion ? `En attente - ${selectedRegion.name}` : "En attente"}
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                Répartition selon la période, le médecin et l’établissement sélectionnés.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: STATUS_COLORS.attenteAujourdhui }}
                />
                Aujourd’hui
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: STATUS_COLORS.retraitAccumule }}
                />
                Après retrait
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: STATUS_COLORS.nonAssigneAccumule }}
                />
                Accumulé
              </span>
            </div>
          </div>
          <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_auto] gap-3 px-5 py-4">
            {waitingBreakdownTotal ? (
              <div className="min-h-0">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Tooltip
                      contentStyle={{ borderRadius: 8, borderColor: "#cbd5e1" }}
                      formatter={(value: number, name: string) => [
                        `${formatNumber(Number(value))} (${percentage(Number(value), waitingBreakdownTotal)}%)`,
                        name,
                      ]}
                    />
                    <Pie
                      data={waitingBreakdownData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      outerRadius="82%"
                      paddingAngle={0}
                      stroke="#ffffff"
                      strokeWidth={2}
                    >
                      {waitingBreakdownData.map((entry) => (
                        <Cell key={entry.name} fill={entry.color} />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                Aucun examen en attente à répartir.
              </div>
            )}
            <div className="grid grid-cols-4 gap-2 border-t border-slate-200 pt-3">
              <div className="rounded-md bg-slate-950 px-3 py-2.5 text-white">
                <div className="truncate text-[10px] font-medium uppercase tracking-wide text-slate-300">
                  Total
                </div>
                <div className="mt-1 text-xl font-semibold tabular-nums">
                  {formatNumber(waitingBreakdownTotal)}
                </div>
              </div>
              {waitingBreakdownData.map((item) => (
                <div
                  key={item.name}
                  className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2.5"
                >
                  <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: item.color }}
                    />
                    <span className="truncate">{item.name}</span>
                  </div>
                  <div className="mt-1 flex items-end justify-between gap-2">
                    <span className="text-xl font-semibold tabular-nums text-slate-950">
                      {formatNumber(item.value)}
                    </span>
                    <span className="pb-0.5 text-xs tabular-nums text-slate-500">
                      {percentage(item.value, waitingBreakdownTotal)}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
