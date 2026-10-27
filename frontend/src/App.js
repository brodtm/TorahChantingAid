import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import HomePage from "./pages/HomePage";
import SessionPage from "./pages/SessionPage";
import CalibrationPage from "./pages/CalibrationPage";
import ProjectorPage from "./pages/ProjectorPage";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/session/:id" element={<SessionPage />} />
        <Route path="/calibrate/:id" element={<CalibrationPage />} />
        <Route path="/projector" element={<ProjectorPage />} />
        <Route path="/projector/:id" element={<ProjectorPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
