import { BrowserRouter, Routes, Route } from 'react-router-dom';
import ProtectedRoute from './components/Auth/ProtectedRoute';
import MainLayout from './components/Layout/MainLayout';
import Dashboard from './pages/Dashboard/Dashboard';
import Research from './pages/Research/Research';
import Workspace from './pages/Workspace/Workspace';
import Tasks from './pages/Tasks/Tasks';
import History from './pages/History/History';
import Experiments from './pages/Experiments/Experiments';
import Observability from './pages/Observability/Observability';
import KnowledgeGraph from './pages/KnowledgeGraph/KnowledgeGraph';
import Settings from './pages/Settings/Settings';
import Login from './pages/Login/Login';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<MainLayout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/research" element={<Research />} />
            <Route path="/workspace" element={<Workspace />} />
            <Route path="/tasks" element={<Tasks />} />
            <Route path="/history" element={<History />} />
            <Route path="/experiments" element={<Experiments />} />
            <Route path="/observability" element={<Observability />} />
            <Route path="/knowledge" element={<KnowledgeGraph />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
