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
  ChevronDown,
  MapPin
} from "lucide-react";
import { Calendar } from "@/components/ui/calendar";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
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
  
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
  const [selectedSlot, setSelectedSlot] = useState<{ day: Date, hour: number } | null>(null);
  const [newSessionDoctor, setNewSessionDoctor] = useState<string>("");
  const [newSessionCount, setNewSessionCount] = useState<number>(1);

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
  const goToday = () => setCurrentDate(new Date());

  const formatHour = (hour: number) => {
    if (hour === 12) return "12 PM";
    if (hour > 12) return `${hour - 12} PM`;
    return `${hour} AM`;
  };

  const getEventColor = (affiliation: string) => {
    if (affiliation.includes("Razi")) return "bg-gradient-to-br from-amber-50/90 to-orange-100/90 text-orange-950 border border-orange-200/80 border-l-[5px] border-l-orange-400 shadow-sm shadow-orange-500/5";
    if (affiliation.includes("libre pratique")) return "bg-gradient-to-br from-blue-50/90 to-indigo-100/90 text-indigo-950 border border-indigo-200/80 border-l-[5px] border-l-indigo-400 shadow-sm shadow-indigo-500/5";
    if (affiliation.includes("Mongi Slim")) return "bg-gradient-to-br from-purple-50/90 to-fuchsia-100/90 text-fuchsia-950 border border-fuchsia-200/80 border-l-[5px] border-l-fuchsia-400 shadow-sm shadow-fuchsia-500/5";
    return "bg-gradient-to-br from-slate-50/90 to-slate-100/90 text-slate-900 border border-slate-200/80 border-l-[5px] border-l-slate-400 shadow-sm shadow-slate-500/5";
  };

  return (
    <div className="flex h-screen flex-col bg-gradient-to-br from-slate-50 via-white to-slate-50/80 overflow-hidden text-slate-900 font-sans relative z-10">
      {/* HEADER */}
      <header className="flex h-16 flex-none items-center justify-between border-b border-slate-200/60 bg-white/70 backdrop-blur-xl px-4 py-2 relative z-50 shadow-[0_1px_3px_0_rgba(0,0,0,0.02)]">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => setSidebarOpen(!sidebarOpen)} className="text-slate-500 rounded-full h-10 w-10 hover:bg-slate-100/80 hover:text-slate-800 transition-all duration-200 active:scale-95">
            <Menu className="h-5 w-5" />
          </Button>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-600 to-indigo-600 text-white font-bold text-lg shadow-lg shadow-blue-600/20 ring-2 ring-white transform transition-transform hover:rotate-3 cursor-default">
              {format(new Date(), 'dd')}
            </div>
            <span className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-700 to-indigo-700 hidden sm:block tracking-tight drop-shadow-sm">Agenda</span>
          </div>
          <div className="ml-8 flex items-center gap-3">
            <Button variant="outline" onClick={goToday} className="rounded-full px-5 h-9 text-sm font-semibold border-slate-200 hover:bg-blue-50/80 hover:border-blue-200 hover:text-blue-700 text-slate-700 transition-all duration-200 shadow-sm active:scale-95">
              Aujourd'hui
            </Button>
            <div className="flex items-center gap-1 ml-2 bg-slate-100/50 rounded-full p-0.5 border border-slate-200/50">
              <Button variant="ghost" size="icon" onClick={prevWeek} className="h-8 w-8 rounded-full text-slate-600 hover:bg-white hover:shadow-sm transition-all duration-200 active:scale-95">
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="icon" onClick={nextWeek} className="h-8 w-8 rounded-full text-slate-600 hover:bg-white hover:shadow-sm transition-all duration-200 active:scale-95">
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
            <h2 className="ml-4 text-xl font-semibold capitalize text-slate-800 tracking-tight w-48">
              {format(currentDate, "MMMM yyyy", { locale: fr })}
            </h2>
          </div>
        </div>

        <div className="flex items-center gap-2">



          
          <div className="ml-2 hidden sm:flex h-9 items-center gap-3">
             <Button variant="ghost" size="icon" className="h-10 w-10 rounded-full text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-colors">
                <div className="grid grid-cols-3 gap-[3px] p-1">
                  {Array.from({length: 9}).map((_, i) => (
                    <div key={i} className="h-1 w-1 bg-current rounded-full" />
                  ))}
                </div>
             </Button>
             <Avatar className="h-9 w-9 border-2 border-white shadow-sm cursor-pointer hover:scale-105 transition-transform ring-2 ring-slate-100">
              <AvatarFallback className="bg-gradient-to-br from-purple-500 to-indigo-500 text-white text-sm font-medium">
                {user?.firstName?.[0] || 'A'}{user?.lastName?.[0] || 'U'}
              </AvatarFallback>
            </Avatar>
          </div>
        </div>
      </header>

      {/* BODY */}
      <div className="flex flex-1 overflow-hidden bg-transparent">
        {/* SIDEBAR */}
        {sidebarOpen && (
          <aside className="w-[280px] flex-none border-r border-slate-200/60 bg-white/40 backdrop-blur-2xl flex flex-col overflow-y-auto hidden md:block relative z-20">
            <div className="p-5">
              <Button className="h-12 w-full rounded-2xl px-4 gap-3 bg-gradient-to-r from-blue-600 to-indigo-600 text-white border-0 hover:from-blue-500 hover:to-indigo-500 hover:shadow-xl hover:shadow-indigo-500/30 transition-all duration-300 shadow-md justify-center text-[15px] font-semibold group active:scale-[0.98]">
                <div className="bg-white/20 rounded-full p-0.5 group-hover:bg-white/30 transition-colors">
                  <Plus className="h-4 w-4 group-hover:rotate-90 transition-transform duration-300" />
                </div>
                Créer
                <ChevronDown className="h-4 w-4 ml-1 opacity-70 group-hover:opacity-100 transition-opacity" />
              </Button>
            </div>
            <div className="px-5 pb-4 border-b border-slate-100/60">
              <Calendar
                mode="single"
                selected={currentDate}
                onSelect={(date) => date && setCurrentDate(date)}
                className="w-full rounded-2xl border-none p-0 [&_.rdp-day]:h-8 [&_.rdp-day]:w-8 [&_.rdp-caption]:h-8 [&_.rdp-day_button:hover]:bg-blue-50/80 [&_.rdp-day_button:hover]:text-blue-700 [&_.rdp-day.rdp-day_selected]:bg-blue-600 [&_.rdp-day.rdp-day_selected]:text-white [&_.rdp-day.rdp-day_selected]:shadow-md [&_.rdp-day.rdp-day_selected]:shadow-blue-600/30 font-medium"
                locale={fr}
              />
            </div>
            
            <div className="flex-1 px-5 py-6 space-y-8 overflow-y-auto custom-scrollbar">
              <div className="relative group">
                <Search className="absolute left-3.5 top-2.5 h-4 w-4 text-slate-400 group-focus-within:text-blue-500 transition-colors" />
                <input 
                  type="text" 
                  placeholder="Rechercher des médecins..." 
                  className="h-10 w-full rounded-xl border border-slate-200 bg-white pl-10 pr-4 text-sm focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all shadow-sm placeholder:text-slate-400"
                />
              </div>
            </div>
          </aside>
        )}

        {/* MAIN CALENDAR GRID */}
        <main className="flex flex-1 flex-col overflow-hidden bg-transparent relative z-0">
          {/* Days Header */}
          <div className="flex flex-none border-b border-slate-200/60 bg-white/60 backdrop-blur-xl z-30 shadow-[0_1px_2px_0_rgba(0,0,0,0.01)]">
            <div className="w-[60px] flex-none text-[10px] font-semibold text-slate-400 flex items-end justify-center pb-3 border-r border-slate-200/60">
              GMT+01
            </div>
            <div className="flex flex-1">
              {weekDays.map((day) => {
                const isSelected = isSameDay(day, currentDate);
                const isActualToday = isSameDay(day, new Date());
                return (
                  <div 
                    key={day.toString()} 
                    onClick={() => setCurrentDate(day)}
                    className="flex-1 flex flex-col items-center py-3 border-r border-slate-200/60 last:border-r-0 min-w-[60px] group cursor-pointer hover:bg-slate-50/50 transition-colors"
                  >
                    <span className={cn("text-[11px] font-bold uppercase tracking-wider mb-1.5 transition-colors duration-200", isSelected ? "text-blue-600" : isActualToday ? "text-slate-800" : "text-slate-500 group-hover:text-slate-700")}>
                      {format(day, 'EEE', { locale: fr }).replace('.', '')}
                    </span>
                    <div className={cn(
                      "flex h-11 w-11 items-center justify-center rounded-full text-xl font-medium transition-all duration-300",
                      isSelected 
                        ? "bg-blue-600 text-white shadow-lg shadow-blue-500/30 ring-2 ring-blue-600 ring-offset-2 ring-offset-white/50" 
                        : isActualToday 
                          ? "text-slate-900 bg-slate-200/60 hover:bg-slate-200" 
                          : "text-slate-700 group-hover:bg-slate-100 group-hover:text-slate-900"
                    )}>
                      {format(day, 'd')}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Scrollable Hours Grid */}
          <div className="flex flex-1 overflow-y-auto relative bg-white/20 custom-scrollbar backdrop-blur-[2px]">
            {/* Time labels axis */}
            <div className="w-[60px] flex-none bg-white/60 backdrop-blur-md border-r border-slate-200/60 relative z-20 pt-4">
              {HOURS.map((hour) => (
                <div key={hour} className="h-20 relative">
                  <span className="absolute -top-2.5 right-3 text-[11px] text-slate-500 font-medium tracking-tight">
                    {formatHour(hour)}
                  </span>
                </div>
              ))}
            </div>

            {/* Grid Cells */}
            <div className="flex flex-1 relative pt-4">
              {/* Background horizontal lines */}
              <div className="absolute inset-0 pointer-events-none z-0 pt-4">
                {HOURS.map((hour) => (
                  <div key={`line-${hour}`} className="h-20 border-b border-slate-200/40 w-full" />
                ))}
              </div>

              {weekDays.map((day, dayIdx) => (
                <div key={dayIdx} className="flex-1 border-r border-slate-200/60 last:border-r-0 relative min-w-[60px] z-10 group/col">
                  {/* Empty cells for hover effect to invite creation */}
                  <div className="absolute inset-0 flex flex-col z-0 pointer-events-auto mt-4">
                    {HOURS.map((hour) => (
                      <div 
                        key={`slot-${hour}`} 
                        className="h-20 w-full hover:bg-blue-50/40 transition-colors duration-200 cursor-pointer border border-transparent hover:border-blue-100" 
                        onClick={() => {
                          setSelectedSlot({ day, hour });
                          setIsCreateDialogOpen(true);
                        }}
                      />
                    ))}
                  </div>

                  {/* Events for this day */}
                  {filteredPlanning.filter(p => isSameDay(p.parsedDate, day)).map((session, i) => {
                    const startHour = 8 + (i * 1.5);
                    const duration = 1.5; 
                    
                    if (startHour > 22) return null;
                    
                    const topPos = (startHour - 8) * 80; 
                    const height = duration * 80;

                    return (
                      <div 
                        key={session.id}
                        className={cn(
                          "absolute left-1 right-2 rounded-xl p-3 text-sm overflow-hidden flex flex-col transition-all duration-300 cursor-pointer z-20 hover:z-30 hover:-translate-y-0.5 hover:shadow-xl backdrop-blur-md ring-1 ring-white/60",
                          getEventColor(session.affiliation)
                        )}
                        style={{ top: `${topPos + 2}px`, height: `${height - 4}px` }}
                      >
                        <span className="font-semibold block truncate leading-snug tracking-tight mb-1">{session.doctorName}</span>
                        <span className="block truncate text-[11px] font-medium opacity-90 flex items-center gap-1.5 mt-auto bg-white/30 w-fit px-1.5 py-0.5 rounded-md">
                          <MapPin className="h-3 w-3 flex-none" />
                          <span className="truncate">{session.hospital}</span>
                        </span>
                      </div>
                    );
                  })}
                  
                  {/* Current Time Indicator for Today */}
                  {isSameDay(day, new Date()) && (
                    <div 
                      className="absolute left-0 right-0 border-t-2 border-rose-500 z-30 pointer-events-none shadow-[0_1px_5px_rgba(244,63,94,0.5)]" 
                      style={{ top: `${(22 - 8) * 80 + 16}px` }}
                    >
                      <div className="absolute -left-1.5 -top-[5px] h-3 w-3 rounded-full bg-rose-500 shadow-md ring-2 ring-white" />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </main>
      </div>

      {/* DIALOG CREATION SESSION */}
      <Dialog open={isCreateDialogOpen} onOpenChange={setIsCreateDialogOpen}>
        <DialogContent className="sm:max-w-[425px] rounded-2xl">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold text-slate-800">Nouvelle session d'examen</DialogTitle>
          </DialogHeader>
          <div className="grid gap-5 py-4">
            {selectedSlot && (
              <div className="text-sm text-slate-500 bg-slate-50 p-3 rounded-xl border border-slate-100 flex items-center gap-2">
                <CalendarIcon className="h-4 w-4 text-blue-500" />
                <span>
                  <span className="font-semibold text-slate-700 capitalize">{format(selectedSlot.day, 'eeee dd MMMM yyyy', { locale: fr })}</span> à <span className="font-semibold text-slate-700">{formatHour(selectedSlot.hour)}</span>
                </span>
              </div>
            )}
            
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="doctor" className="text-right text-slate-600 font-medium">Médecin</Label>
              <div className="col-span-3">
                <Select value={newSessionDoctor} onValueChange={setNewSessionDoctor}>
                  <SelectTrigger id="doctor" className="rounded-xl border-slate-200 focus:ring-blue-500">
                    <SelectValue placeholder="Sélectionner un médecin" />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl">
                    {doctors.map(doc => (
                      <SelectItem key={doc} value={doc}>{doc}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="count" className="text-right text-slate-600 font-medium">Nb. examens</Label>
              <Input 
                id="count" 
                type="number" 
                min="1"
                className="col-span-3 rounded-xl border-slate-200 focus:ring-blue-500"
                value={newSessionCount}
                onChange={(e) => setNewSessionCount(parseInt(e.target.value) || 1)}
              />
            </div>
          </div>
          <DialogFooter className="gap-2 sm:gap-0 mt-2">
            <Button variant="outline" onClick={() => setIsCreateDialogOpen(false)} className="rounded-xl">Annuler</Button>
            <Button onClick={() => {
              setIsCreateDialogOpen(false);
              setNewSessionDoctor("");
              setNewSessionCount(1);
            }} className="rounded-xl bg-blue-600 hover:bg-blue-700 text-white shadow-md shadow-blue-500/20 transition-all">Assigner</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
