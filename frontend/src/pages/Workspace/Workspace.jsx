import { useState, useRef, useEffect } from 'react';
import { listSessions, getSessionFiles, getFileContent, createSession } from '../../services/api';
import { marked } from 'marked';
import { ResearchWebSocket } from '../../services/websocket';
import { 
  FileText, Play, Square, Folder, File, Activity, Beaker
} from 'lucide-react';

export default function Workspace() {
  // --- Workspace State ---
  const [sessions, setSessions] = useState([]);
  const [selectedSession, setSelectedSession] = useState(null);
  const [files, setFiles] = useState([]);
  const [fileContent, setFileContent] = useState(null);
  const [selectedPath, setSelectedPath] = useState(null);
  const [experiments, setExperiments] = useState([]);
  const [viewMode, setViewMode] = useState('file'); // 'file' or 'experiments'

  // --- Research State ---
  const [query, setQuery] = useState('');
  const [events, setEvents] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [todos, setTodos] = useState([]);
  const [status, setStatus] = useState('idle');
  const eventsEndRef = useRef(null);
  const wsRef = useRef(null);

  useEffect(() => {
    refreshSessions();
  }, []);

  const refreshSessions = () => {
    listSessions().then(data => {
      const s = data.sessions || [];
      setSessions(s);
      if (s.length > 0 && !selectedSession) setSelectedSession(s[0].id);
    }).catch(() => {});
  };

  useEffect(() => {
    if (selectedSession) {
      getSessionFiles(selectedSession).then(data => setFiles(data.files || [])).catch(() => setFiles([]));
      setFileContent(null);
      setSelectedPath(null);
      
      // Fetch experiments
      fetch(`/api/sessions/${selectedSession}/experiments`)
        .then(res => res.json())
        .then(data => setExperiments(data.experiments || []))
        .catch(() => setExperiments([]));
    }
  }, [selectedSession]);

  const openFile = async (name) => {
    try {
      const data = await getFileContent(selectedSession, name);
      setFileContent(data.content);
      setSelectedPath(name);
      setViewMode('file');
    } catch { setFileContent('Error loading file.'); }
  };

  // --- Research Logic ---
  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events]);

  const startResearch = async () => {
    if (!query.trim() || status === 'running') return;
    setStatus('connecting');
    setEvents([]); setMetrics(null); setTodos([]);
    try {
      const session = await createSession(query);
      refreshSessions();
      setSelectedSession(session.id); // Switch context to new session
      
      const ws = new ResearchWebSocket(session.id, {
        onOpen: () => {
          setStatus('running');
          ws.send(JSON.stringify({ query }));
        },
        onEvent: (event) => setEvents(prev => [...prev, { ...event, timestamp: Date.now() }]),
        onMetrics: (data) => setMetrics(data),
        onTodoUpdate: (data) => setTodos(data.todos || []),
        onComplete: () => {
          setStatus('completed');
          // Refresh files
          getSessionFiles(session.id).then(data => setFiles(data.files || []));
        },
        onError: (data) => setEvents(prev => [...prev, { type: 'error', data, timestamp: Date.now() }]),
        onClose: () => { if (status === 'running') setStatus('completed'); },
      });
      wsRef.current = ws;
      ws.connect();
      setQuery(''); // Clear query after send
    } catch (err) {
      setStatus('error');
      setEvents(prev => [...prev, { type: 'error', data: { message: err.message }, timestamp: Date.now() }]);
    }
  };

  return (
    <div className="flex h-full w-full bg-background overflow-hidden relative">
      
      {/* Left Panel: Files & Context */}
      <div className="w-72 border-r border-border bg-card/40 flex flex-col shrink-0 flex-none h-full max-h-screen">
        <div className="p-4 border-b border-border bg-card">
          <h2 className="text-sm font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
            <Folder className="w-4 h-4" /> Workspace Explorer
          </h2>
        </div>
        
        <div className="px-4 py-3 bg-card/60 border-b border-border">
          <label className="text-xs font-semibold text-muted-foreground mb-1 block">Active Session</label>
          <select 
            className="w-full bg-background border border-border text-sm rounded cursor-pointer p-1"
            value={selectedSession || ''}
            onChange={e => setSelectedSession(e.target.value)}
          >
            {sessions.map(s => <option key={s.id} value={s.id}>{s.title || "Untitled"}</option>)}
          </select>
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-2">
          <div className="text-xs font-semibold text-muted-foreground uppercase px-2 py-2">Research Artifacts</div>
          {files.map((f, i) => (
             <div 
               key={i} 
               onClick={() => !f.is_dir && openFile(f.name)}
               className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer text-sm mb-1 transition-colors ${selectedPath === f.name ? 'bg-primary/20 text-primary font-medium' : 'hover:bg-muted text-foreground/80'}`}
             >
               {f.is_dir ? <Folder className="w-4 h-4 text-primary opacity-60" /> : <File className="w-4 h-4 text-muted-foreground" />}
               <span className="truncate flex-1">{f.name}</span>
             </div>
          ))}

          <div className="text-xs font-semibold text-muted-foreground uppercase px-2 mt-4 py-2 border-t border-border">Logs & Metrics</div>
          <div 
            onClick={() => setViewMode('experiments')}
            className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer text-sm transition-colors ${viewMode === 'experiments' ? 'bg-primary/20 text-primary font-medium' : 'hover:bg-muted text-foreground/80'}`}
          >
            <Beaker className="w-4 h-4 text-purple-400" />
            <span className="truncate flex-1">Experiment Logs</span>
            <span className="text-[10px] bg-primary/20 px-1.5 rounded-full">{experiments.length}</span>
          </div>
        </div>
      </div>

      {/* Middle Panel: Viewer */}
      <div className="flex-1 bg-background flex flex-col min-w-0 h-full overflow-hidden border-r border-border relative">
        <div className="h-14 border-b border-border flex items-center px-4 justify-between bg-card/50 flex-none z-10 sticky top-0">
           <h2 className="text-sm font-semibold flex items-center gap-2">
             {viewMode === 'file' ? (
               selectedPath ? <><FileText className="w-4 h-4 text-primary" /> {selectedPath}</> : 'Document Viewer'
             ) : (
               <><Beaker className="w-4 h-4 text-purple-400" /> Session Experiments</>
             )}
           </h2>
        </div>
        
        <div className="flex-1 overflow-y-auto p-8 relative flex-grow min-h-0">
          {viewMode === 'file' ? (
             fileContent ? (
               <div className="bg-card border border-border shadow-sm rounded-lg p-10 max-w-4xl mx-auto prose prose-invert">
                 <div dangerouslySetInnerHTML={{ __html: marked(fileContent) }} />
               </div>
             ) : (
               <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
                 <FileText className="w-16 h-16 mb-4 opacity-10" />
                 <p>Select a file to view its contents.</p>
               </div>
             )
          ) : (
             <div className="max-w-3xl mx-auto space-y-4">
               {experiments.length === 0 ? (
                  <div className="text-center py-10 text-muted-foreground bg-card border border-border rounded-xl">No experiments logged in this session.</div>
               ) : (
                  experiments.map(exp => (
                    <div key={exp.id} className="bg-card border border-border p-6 rounded-xl hover:shadow-lg transition">
                       <h4 className="font-semibold text-xs uppercase tracking-widest mb-2 text-primary">Hypothesis</h4>
                       <p className="text-sm text-foreground mb-6 leading-relaxed">{exp.hypothesis}</p>
                       <h4 className="font-semibold text-xs uppercase tracking-widest mb-2 text-accent">Result</h4>
                       <p className="text-sm text-green-400 font-mono bg-black p-4 rounded-lg leading-relaxed">{exp.result}</p>
                    </div>
                  ))
               )}
             </div>
          )}
        </div>
      </div>

      {/* Right Panel: Active Agent Chat */}
      <div className="w-[400px] bg-card flex flex-col shrink-0 flex-none h-full max-h-screen">
        <div className="h-14 border-b border-border flex items-center px-4 justify-between bg-card shrink-0">
          <h2 className="text-sm font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
             <Activity className="w-4 h-4" /> Agent Partner
          </h2>
          {status === 'running' && <span className="flex w-2.5 h-2.5 bg-green-500 rounded-full animate-pulse shadow-[0_0_8px_rgba(34,197,94,0.6)]"></span>}
        </div>
        
        {/* Event Stream */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3 text-sm min-h-0 relative">
           {events.length === 0 ? (
             <div className="text-center text-muted-foreground mt-12 bg-background border border-border p-6 rounded-xl">
               <Activity className="w-8 h-8 mx-auto mb-3 opacity-20" />
               <p>Give me a research topic or ask me a question.</p>
             </div>
           ) : (
             events.map((ev, i) => (
                <div key={i} className="bg-background border border-border/60 rounded-lg p-3.5 shadow-sm">
                  {ev.type === 'message' && <div className="text-foreground leading-relaxed">{ev.data.content}</div>}
                  {ev.type === 'tool_call' && <div className="text-primary font-mono text-xs flex items-center gap-2"><span className="text-lg">⚙</span> Running: {ev.data.tool}</div>}
                  {ev.type === 'tool_result' && <div className="text-muted-foreground font-mono text-xs truncate pl-6 opacity-70">↳ Output length: {String(ev.data.result).length}</div>}
                  {(ev.type === 'thinking' || ev.type === 'status') && <div className="text-accent text-xs animate-pulse font-medium">{ev.data.message}</div>}
                  {ev.type === 'error' && <div className="text-destructive text-sm font-semibold p-2 bg-destructive/10 rounded">❌ {ev.data.message}</div>}
                  {ev.type === 'complete' && <div className="text-green-500 font-bold mt-2 pt-2 border-t border-border/50 text-center">🏁 Task Completed</div>}
                </div>
             ))
           )}
           <div ref={eventsEndRef} className="h-4" />
        </div>

        {/* Input area */}
        <div className="p-4 border-t border-border bg-card/80 backdrop-blur shrink-0">
          <div className="relative">
            <textarea
               className="w-full bg-background border border-border rounded-xl p-3 pr-12 text-sm focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary resize-none shadow-inner"
               rows="3"
               placeholder="Issue a command or start new research..."
               value={query}
               onChange={e => setQuery(e.target.value)}
               onKeyDown={e => {
                 if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); startResearch(); }
               }}
            />
            <div className="absolute bottom-3 right-3 flex gap-2">
               {status === 'running' ? (
                  <button onClick={() => wsRef.current?.close()} className="bg-destructive hover:bg-destructive/90 text-destructive-foreground p-1.5 rounded-md transition-colors" title="Stop">
                    <Square className="w-4 h-4 fill-current" />
                  </button>
               ) : (
                  <button onClick={startResearch} disabled={!query.trim()} className="bg-primary hover:bg-primary/90 text-primary-foreground p-1.5 rounded-md transition-colors disabled:opacity-50" title="Run">
                    <Play className="w-4 h-4 fill-current ml-0.5" />
                  </button>
               )}
            </div>
          </div>
        </div>
      </div>

    </div>
  );
}
