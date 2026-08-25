import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import DynamicSkillBackground from '../components/DynamicSkillBackground';
import ArchiveReturnHome from '../components/ArchiveReturnHome';
import SpaceHomePage from '../pages/SpaceHomePage';
import SpaceGraphPage from '../pages/SpaceGraphPage';
import ApplicantFlowPage from '../pages/ApplicantFlowPage';
import HRWorkspacePage from '../pages/HRWorkspacePage';
import EmergingJobsPage from '../pages/EmergingJobsPage';
import ReviewCenterPage from '../pages/ReviewCenterPage';
import AdminCenterPage from '../pages/AdminCenterPage';

const RoutedApp = () => {
  const location = useLocation();
  const isArchiveHome = location.pathname === '/';

  return (
    <div className="app-shell">
      <DynamicSkillBackground />
      {!isArchiveHome && <ArchiveReturnHome />}
      <main className="app-content">
        <Routes>
          <Route path="/" element={<SpaceHomePage />} />
          <Route path="/graph" element={<SpaceGraphPage />} />
          <Route path="/applicant" element={<ApplicantFlowPage />} />
          <Route path="/resume-match" element={<ApplicantFlowPage />} />
          <Route path="/hr" element={<HRWorkspacePage />} />
          <Route path="/hr-match" element={<HRWorkspacePage />} />
          <Route path="/emerging" element={<EmergingJobsPage />} />
          <Route path="/new-jobs" element={<EmergingJobsPage />} />
          <Route path="/review" element={<ReviewCenterPage />} />
          <Route path="/admin" element={<AdminCenterPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
};

const AppRouter = () => (
  <BrowserRouter>
    <RoutedApp />
  </BrowserRouter>
);

export default AppRouter;
