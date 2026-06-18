import { Brain, Target, Check, Download, ChevronDown, Wand2 } from "lucide-react";

export function AIPanel() {
  return (
    <div className="rounded-xl border border-slate-700 bg-[#0A1128] text-slate-200 flex flex-col h-[600px]">
      <div className="p-4 border-b border-slate-800 bg-[#0A1128]">
        <h2 className="text-sm font-semibold flex items-center gap-2 text-white">
          <Wand2 className="h-4 w-4 text-blue-400" />
          Panneau d'Analyse AI & Rapport
        </h2>
      </div>
      
      <div className="p-5 space-y-6 flex-1 overflow-y-auto custom-scrollbar">
        {/* IA Analysis */}
        <div className="space-y-4">
          <h3 className="text-sm font-bold text-white">Interprétation de l'IA</h3>
          
          <div className="space-y-4">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  <Brain className="h-4 w-4 text-emerald-400" />
                  <span className="text-slate-200">Hémorragie</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                  <span className="text-emerald-400 font-medium">2%</span>
                </div>
              </div>
              <p className="text-xs text-slate-400 pl-6 leading-relaxed">
                - Pas d'hémorragie intracrânienne détectée<br/>
                - Anomalie de densité non-spécifique
              </p>
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  <Target className="h-4 w-4 text-amber-400" />
                  <span className="text-slate-200">Détection de masse focalisée</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                  <span className="text-amber-400 font-medium">40%</span>
                </div>
              </div>
              <p className="text-xs text-slate-400 pl-6 leading-relaxed">
                - Anomalie de densité non-spécifique
              </p>
            </div>
          </div>
        </div>

        {/* Report */}
        <div className="space-y-3">
          <h3 className="text-sm font-bold text-white">Rapport Préliminaire</h3>
          <textarea 
            className="w-full h-36 bg-[#121936] border border-slate-700 rounded-lg p-3 text-xs text-slate-300 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 resize-none"
            defaultValue={"Compte-rendu d'examen CT du crâne du 11 Mai 2023.\n\nPas d'hémorragie intracrânienne évidente. Zone de densité iso-intense dans la région [Spécifier] nécessitant une corrélation clinique..."}
          />
          <div className="space-y-2 pt-2">
            <button className="w-full bg-emerald-600 hover:bg-emerald-700 text-white rounded-md py-2.5 text-xs font-medium transition flex items-center justify-center gap-2">
              Valider le Rapport
            </button>
            <button className="w-full bg-emerald-600 hover:bg-emerald-700 text-white rounded-md py-2.5 text-xs font-medium transition flex items-center justify-center gap-2">
              Exporter PDF
            </button>
          </div>
        </div>
      </div>

      <div className="p-3 border-t border-slate-800 bg-[#0A1128] flex items-center justify-between cursor-pointer hover:bg-[#121936] transition rounded-b-xl">
        <span className="text-xs font-medium text-blue-500">Outils de Segmentation</span>
        <ChevronDown className="h-4 w-4 text-blue-500" />
      </div>
    </div>
  );
}
