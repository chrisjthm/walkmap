import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import AppLayout from "./layouts/AppLayout";
import { RoutePlannerProvider } from "./components/routePlanner";
import ExplorePanel from "./pages/ExplorePanel";
import MapHome from "./pages/MapHome";
import PlanPanel from "./pages/PlanPanel";
import RegisterPanel from "./pages/RegisterPanel";
import LoginPanel from "./pages/LoginPanel";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RoutePlannerProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<MapHome />} />
              <Route path="plan" element={<PlanPanel />} />
              <Route path="explore" element={<ExplorePanel />} />
              <Route path="login" element={<LoginPanel />} />
              <Route path="register" element={<RegisterPanel />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </RoutePlannerProvider>
    </QueryClientProvider>
  );
}
