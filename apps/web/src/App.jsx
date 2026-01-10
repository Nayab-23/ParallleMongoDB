import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import DemoChat from "./pages/DemoChat";
import ErrorBoundary from "./components/ErrorBoundary";

export default function App() {
  return (
    <ErrorBoundary message="App encountered an error. Please refresh.">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<DemoChat />} />
          <Route path="/index.html" element={<Navigate to="/" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
