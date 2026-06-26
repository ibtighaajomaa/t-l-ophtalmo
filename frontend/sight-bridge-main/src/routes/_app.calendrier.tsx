import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState, useEffect } from "react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { useAuth } from "@/lib/auth-context";
import { MOCK_PLANNING, PlanningSession } from "@/lib/mock-planning";
import { fetchExams } from "@/lib/exam-api";
import type { Exam } from "@/lib/mock-worklist";
import { 
  ChevronLeft, 
  ChevronRight, 
  Search, 
  Settings, 
  HelpCircle, 
  Menu, 
  Plus, 
  Calendar as CalendarIcon,
  ChevronDown
} from "lucide-react";
import { Calendar } from "@/components/ui/calendar";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { fr } from "date-fns/locale";
import { 
  format, 
  addDays, 
  startOfWeek, 
  addWeeks, 
  subWeeks, 
  isSameDay, 
  parse,
  isToday
} from "date-fns";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/_app/calendrier")({
  component: () => (
    <ProtectedRoute roles={["Admin", "Chef", "Medecin", "Resident"]}>
      <CalendrierPage />
    </ProtectedRoute>
  ),
});

// Helper pour parser la date "Jeudi 08 janvier 2026"
function parseFrenchDate(dateStr: string): Date | null {
  try {
    return parse(dateStr.toLowerCase(), 'eeee dd MMMM yyyy', new Date(), { locale: fr });
  } catch (e) {
    return null;
  }
}

const HOURS = Array.from({ length: 16 }, (_, i) => i + 8); // 8 AM to 11 PM

function CalendrierPage() {
  const { user } = useAuth();
  
  // Date de référence pour correspondre aux mocks (Juin 2026)
  const defaultDate = new Date(2026, 5, 26);
  const [currentDate, setCurrentDate] = useState(defaultDate);
  const [exams, setExams] = useState<Exam[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  useEffect(() => {
    fetchExams({ page_size: 100 })
      .then((r) => setExams(r.exams))
      .catch(() => {});
  }, []);

  const normalize = (name: string) => name.toLowerCase().replace(/^(dr\.|pr|dr)\s+/i, '').trim();

  const parsedPlanning = useMemo(() => {
    return MOCK_PLANNING.map(session => {
      let parsed = parseFrenchDate(session.date);
      // Fallback si la date ne se parse pas bien
      if (isNaN(parsed?.getTime() || NaN)) {
        parsed = new Date();
      }
      return {
        ...session,
        parsedDate: parsed as Date
      };
    }).filter(s => s.parsedDate !== null);
  }, []);

  const doctors = useMemo(() => {
    const docs = new Set<string>();
    parsedPlanning.forEach(p => docs.add(p.doctorName));
    return Array.from(docs).sort();
  }, [parsedPlanning]);

  const [selectedDoctors, setSelectedDoctors] = useState<Set<string>>(new Set(doctors));

  useEffect(() => {
     if (user?.role === "Admin") {
       setSelectedDoctors(new Set(doctors));
     } else if (user?.firstName) {
       setSelectedDoctors(new Set([`Dr ${user.firstName} ${user.lastName}`]));
     } else {
       setSelectedDoctors(new Set(doctors));
     }
  }, [doctors, user]);

  const toggleDoctor = (doc: string) => {
    const next = new Set(selectedDoctors);
    if (next.has(doc)) next.delete(doc);
    else next.add(doc);
    setSelectedDoctors(next);
  };

  const filteredPlanning = useMemo(() => {
    return parsedPlanning.filter(p => selectedDoctors.has(p.doctorName));
  }, [parsedPlanning, selectedDoctors]);

  const weekStart = startOfWeek(currentDate, { weekStartsOn: 0 }); // Sunday as start

  const weekDays = useMemo(() => {
    return Array.from({ length: 7 }).map((_, i) => addDays(weekStart, i));
  }, [weekStart]);

  const nextWeek = () => setCurrentDate(addWeeks(currentDate, 1));
  const prevWeek = () => setCurrentDate(subWeeks(currentDate, 1));
  const goToday = () => setCurrentDate(defaultDate); // Ou new Date()

  const formatHour = (hour: number) => {
    if (hour === 12) return "12 PM";
    if (hour > 12) return `${hour - 12} PM`;
    return `${hour} AM`;
  };

  const getEventColor = (affiliation: string) => {
    if (affiliation.includes("Razi")) return "bg-yellow-100 text-yellow-800 border-yellow-300 hover:bg-yellow-200";
    if (affiliation.includes("libre pratique")) return "bg-blue-100 text-blue-800 border-blue-300 hover:bg-blue-200";
    if (affiliation.includes("Mongi Slim")) return "bg-purple-100 text-purple-800 border-purple-300 hover:bg-purple-200";
    return "bg-slate-100 text-slate-800 border-slate-300 hover:bg-slate-200";
  };

  return (
    <div className="flex h-[calc(100vh-2rem)] flex-col bg-white overflow-hidden text-slate-900 font-sans -m-6 rounded-tl-xl border border-slate-200 shadow-sm relative z-10">
      {/* HEADER */}
      <header className="flex h-16 flex-none items-center justify-between border-b border-slate-200 px-4 py-2 bg-white">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => setSidebarOpen(!sidebarOpen)} className="text-slate-600 rounded-full h-10 w-10 hover:bg-slate-100">
            <Menu className="h-5 w-5" />
          </Button>
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-blue-600 text-white font-bold text-lg shadow-sm">
              {format(defaultDate, 'dd')}
            </div>
            <span className="text-xl font-normal text-slate-700 hidden sm:block">Agenda</span>
          </div>
          <div className="ml-6 flex items-center gap-2">
            <Button variant="outline" onClick={goToday} className="rounded-full px-4 h-9 text-sm font-medium border-slate-300 hover:bg-slate-50 text-slate-700">
              Aujourd'hui
            </Button>
            <div className="flex items-center gap-1 ml-2">
              <Button variant="ghost" size="icon" onClick={prevWeek} className="h-8 w-8 rounded-full text-slate-600 hover:bg-slate-100">
                <ChevronLeft className="h-5 w-5" />
              </Button>
              <Button variant="ghost" size="icon" onClick={nextWeek} className="h-8 w-8 rounded-full text-slate-600 hover:bg-slate-100">
                <ChevronRight className="h-5 w-5" />
              </Button>
            </div>
            <h2 className="ml-4 text-[22px] font-normal capitalize text-slate-700">
              {format(currentDate, "MMMM yyyy", { locale: fr })}
            </h2>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" className="h-10 w-10 rounded-full text-slate-600 hover:bg-slate-100">
            <Search className="h-5 w-5" />
          </Button>
          <Button variant="ghost" size="icon" className="h-10 w-10 rounded-full text-slate-600 hover:bg-slate-100">
            <HelpCircle className="h-5 w-5" />
          </Button>
          <Button variant="ghost" size="icon" className="h-10 w-10 rounded-full text-slate-600 hover:bg-slate-100">
            <Settings className="h-5 w-5" />
          </Button>
          
          <Button variant="outline" className="ml-2 gap-2 h-9 rounded-md px-3 hidden sm:flex font-medium border-slate-300 hover:bg-slate-50 text-slate-700">
            Semaine <ChevronDown className="h-4 w-4 text-slate-500" />
          </Button>
          
          <div className="ml-4 hidden sm:flex h-9 items-center gap-2">
             <Button variant="ghost" size="icon" className="h-10 w-10 rounded-full text-slate-600 hover:bg-slate-100">
                <div className="grid grid-cols-3 gap-0.5 p-1">
                  {Array.from({length: 9}).map((_, i) => (
                    <div key={i} className="h-[3px] w-[3px] bg-slate-600 rounded-full" />
                  ))}
                </div>
             </Button>
             <Avatar className="h-8 w-8 border border-slate-200 cursor-pointer">
              <AvatarFallback className="bg-purple-600 text-white text-xs font-medium">
                {user?.firstName?.[0] || 'A'}{user?.lastName?.[0] || 'U'}
              </AvatarFallback>
            </Avatar>
          </div>
        </div>
      </header>

      {/* BODY */}
      <div className="flex flex-1 overflow-hidden bg-white">
        {/* SIDEBAR */}
        {sidebarOpen && (
          <aside className="w-64 flex-none border-r border-slate-200 bg-white flex flex-col overflow-y-auto hidden md:block">
            <div className="p-4 pt-5 pb-3">
              <Button className="h-[48px] rounded-full px-4 gap-3 bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 hover:text-slate-800 hover:shadow-md transition-all shadow-sm w-fit justify-start text-sm font-medium">
                <Plus className="h-6 w-6 text-slate-600" />
                Créer
                <ChevronDown className="h-4 w-4 text-slate-500 ml-1" />
              </Button>
            </div>
            <div className="px-4 pb-2">
              <Calendar
                mode="single"
                selected={currentDate}
                onSelect={(date) => date && setCurrentDate(date)}
                className="w-full rounded-md border-none p-0 [&_.rdp-day]:h-8 [&_.rdp-day]:w-8 [&_.rdp-caption]:h-8"
                locale={fr}
              />
            </div>
            <div className="mt-2 px-4">
              <div className="relative">
                <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
                <input 
                  type="text" 
                  placeholder="Rechercher des médecins..." 
                  className="h-9 w-full rounded-md border-none bg-slate-100 pl-9 pr-3 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                />
              </div>
            </div>

            <div className="mt-6 flex-1 px-4 space-y-6 pb-6">
              <div>
                <h3 className="mb-2 text-sm font-medium text-slate-800 flex items-center justify-between cursor-pointer hover:bg-slate-50 p-1 -ml-1 rounded">
                  Pages de réservation
                  <Plus className="h-4 w-4 text-slate-500" />
                </h3>
              </div>

              <div>
                <h3 className="mb-3 text-sm font-medium text-slate-800 flex items-center justify-between cursor-pointer hover:bg-slate-50 p-1 -ml-1 rounded">
                  Mes agendas
                  <ChevronDown className="h-4 w-4 text-slate-500" />
                </h3>
                <div className="space-y-2 max-h-[250px] overflow-y-auto pr-2 custom-scrollbar">
                  {doctors.map((doc, idx) => {
                    const colors = [
                      "data-[state=checked]:bg-blue-500 data-[state=checked]:border-blue-500",
                      "data-[state=checked]:bg-green-500 data-[state=checked]:border-green-500",
                      "data-[state=checked]:bg-purple-500 data-[state=checked]:border-purple-500",
                      "data-[state=checked]:bg-orange-500 data-[state=checked]:border-orange-500"
                    ];
                    return (
                      <label key={doc} className="flex items-center gap-3 text-sm text-slate-700 cursor-pointer hover:bg-slate-50 p-1 rounded -ml-1">
                        <Checkbox 
                          checked={selectedDoctors.has(doc)} 
                          onCheckedChange={() => toggleDoctor(doc)}
                          className={cn("rounded border-slate-300", colors[idx % colors.length])}
                        />
                        <span className="truncate" title={doc}>{doc}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
              
              <div>
                <h3 className="mb-3 text-sm font-medium text-slate-800 flex items-center justify-between cursor-pointer hover:bg-slate-50 p-1 -ml-1 rounded">
                  Autres agendas
                  <Plus className="h-4 w-4 text-slate-500" />
                </h3>
                <label className="flex items-center gap-3 text-sm text-slate-700 cursor-pointer p-1 -ml-1 hover:bg-slate-50 rounded">
                  <Checkbox className="rounded border-slate-300 data-[state=checked]:bg-slate-700 data-[state=checked]:border-slate-700" defaultChecked />
                  <span className="truncate">Jours fériés en Tunisie</span>
                </label>
              </div>
            </div>
          </aside>
        )}

        {/* MAIN CALENDAR GRID */}
        <main className="flex flex-1 flex-col overflow-hidden bg-white">
          {/* Days Header */}
          <div className="flex flex-none border-b border-slate-200">
            <div className="w-[50px] flex-none text-[10px] text-slate-500 flex items-end justify-center pb-2 border-r border-slate-200 bg-white z-10">
              GMT+01
            </div>
            <div className="flex flex-1">
              {weekDays.map((day) => {
                const today = isSameDay(day, defaultDate); // Simulate today as defaultDate
                return (
                  <div key={day.toString()} className="flex-1 flex flex-col items-center py-2 border-r border-slate-200 last:border-r-0 min-w-[60px]">
                    <span className={cn("text-[11px] font-medium uppercase tracking-wider mb-1", today ? "text-blue-600" : "text-slate-500")}>
                      {format(day, 'EEE', { locale: fr }).replace('.', '')}
                    </span>
                    <div className={cn(
                      "flex h-11 w-11 items-center justify-center rounded-full text-2xl font-normal transition-colors",
                      today ? "bg-blue-600 text-white" : "text-slate-700 hover:bg-slate-100 cursor-pointer"
                    )}>
                      {format(day, 'd')}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Scrollable Hours Grid */}
          <div className="flex flex-1 overflow-y-auto relative">
            {/* Time labels axis */}
            <div className="w-[50px] flex-none bg-white border-r border-slate-200 relative z-20 pt-4">
              {HOURS.map((hour) => (
                <div key={hour} className="h-16 relative">
                  <span className="absolute -top-2.5 right-2 text-[10px] text-slate-500 font-medium">
                    {formatHour(hour)}
                  </span>
                </div>
              ))}
            </div>

            {/* Grid Cells */}
            <div className="flex flex-1 relative pt-4">
              {weekDays.map((day, dayIdx) => (
                <div key={dayIdx} className="flex-1 border-r border-slate-200 last:border-r-0 relative min-w-[60px]">
                  {/* Grid lines */}
                  {HOURS.map((hour) => (
                    <div key={hour} className="h-16 border-b border-slate-100 w-full" />
                  ))}

                  {/* Events for this day */}
                  {filteredPlanning.filter(p => isSameDay(p.parsedDate, day)).map((session, i) => {
                    const startHour = 8 + (i * 1.5);
                    const duration = 1.5; 
                    
                    if (startHour > 22) return null;
                    
                    const topPos = (startHour - 8) * 64; 
                    const height = duration * 64;

                    return (
                      <div 
                        key={session.id}
                        className={cn(
                          "absolute left-0.5 right-1.5 rounded-[4px] border p-1.5 text-xs shadow-sm overflow-hidden flex flex-col transition-all cursor-pointer z-10 hover:z-20 hover:shadow-md",
                          getEventColor(session.affiliation)
                        )}
                        style={{ top: `${topPos}px`, height: `${height - 2}px` }}
                      >
                        <span className="font-semibold block truncate leading-tight text-slate-900">{session.doctorName}</span>
                        <span className="block truncate text-[10px] opacity-90 mt-0.5 text-slate-700">{session.hospital}</span>
                      </div>
                    );
                  })}
                  
                  {/* Current Time Line (Red) - Mocked to 10 PM for Friday Jun 26 2026 */}
                  {isSameDay(day, defaultDate) && (
                    <div 
                      className="absolute left-0 right-0 border-t-2 border-red-500 z-30 pointer-events-none" 
                      style={{ top: `${(22 - 8) * 64}px` }}
                    >
                      <div className="absolute -left-1.5 -top-[5px] h-[10px] w-[10px] rounded-full bg-red-500" />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
