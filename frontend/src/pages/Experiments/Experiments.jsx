import React, { useState, useEffect } from 'react';
import { Beaker, Search, Activity, AlignLeft, CheckCircle2 } from 'lucide-react';

export default function Experiments() {
  const [sessions, setSessions] = useState([]);
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [experiments, setExperiments] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch('/api/sessions')
      .then(res => res.json())
      .then(data => {
        if (data.sessions) {
          setSessions(data.sessions);
          if (data.sessions.length > 0) {
             setSelectedSessionId(data.sessions[0].id);
          }
        }
      });
  }, []);

  useEffect(() => {
    if (!selectedSessionId) return;
    setLoading(true);
    fetch(`/api/sessions/${selectedSessionId}/experiments`)
      .then(res => res.json())
      .then(data => {
        setExperiments(data.experiments || []);
        setLoading(false);
      });
  }, [selectedSessionId]);

  return (
    <div className="p-8 h-full overflow-y-auto">
      <div className="mb-8">
        <h1 className="text-3xl border-b border-border pb-4 flex items-center gap-3">
          <Beaker className="w-8 h-8 text-primary" />
          Experiment Tracking
        </h1>
        <p className="text-muted-foreground mt-2">
          Track hypotheses, methodologies, and results across your research sessions.
        </p>
      </div>

      <div className="mb-6 flex items-center gap-4">
        <label className="text-sm font-medium">Select Session:</label>
        <select 
          value={selectedSessionId} 
          onChange={(e) => setSelectedSessionId(e.target.value)}
          className="bg-card border border-border rounded-md px-4 py-2 w-full max-w-md focus:outline-none focus:ring-2 focus:ring-primary"
        >
          {sessions.map(s => (
            <option key={s.id} value={s.id}>
              {s.title || 'Untitled Session'} ({new Date(s.created_at).toLocaleDateString()})
            </option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Activity className="animate-spin w-8 h-8 text-primary" /></div>
      ) : (
        <div className="space-y-6">
          {experiments.length === 0 ? (
             <div className="text-center py-12 text-muted-foreground bg-card rounded-lg border border-border">
                No experiments logged for this session yet.
             </div>
          ) : (
             experiments.map((exp, idx) => (
                <div key={exp.id} className="relative pl-8 pb-8 border-l-2 border-primary/20 last:border-0 last:pb-0">
                  <div className="absolute -left-[11px] top-0 bg-background border-2 border-primary w-5 h-5 rounded-full flex items-center justify-center">
                    <span className="text-[10px] font-bold text-primary">{idx + 1}</span>
                  </div>
                  <div className="bg-card border border-border/50 rounded-xl p-6 shadow-sm">
                    <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
                      <div>
                        <h4 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-3">
                          <Search className="w-4 h-4" /> Hypothesis
                        </h4>
                        <div className="bg-background rounded-lg p-4 text-sm leading-relaxed border border-border/50">
                           {exp.hypothesis}
                        </div>
                      </div>
                      <div>
                        <h4 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-3">
                          <AlignLeft className="w-4 h-4" /> Approach
                        </h4>
                        <div className="bg-background rounded-lg p-4 text-sm leading-relaxed border border-border/50">
                           {exp.approach || "No approach specified."}
                        </div>
                      </div>
                      <div className="md:col-span-2 space-y-4">
                        <h4 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-0 border-t border-border/50 pt-4">
                          <Activity className="w-4 h-4" /> Result
                        </h4>
                        <div className="text-sm font-mono bg-black/40 text-green-400 p-4 rounded-lg overflow-auto">
                           {exp.result || "Awaiting results..."}
                        </div>
                      </div>
                      <div className="md:col-span-2 space-y-4">
                        <h4 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-0">
                          <CheckCircle2 className="w-4 h-4" /> Conclusion
                        </h4>
                        <div className="bg-primary/10 border border-primary/20 p-4 rounded-lg text-sm text-foreground">
                           {exp.conclusion || "No conclusion drawn yet."}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
             ))
          )}
        </div>
      )}
    </div>
  );
}
