import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Link, RouterProvider, useParams } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ThemeProvider } from "./lib/theme";
import { JobDetailPage } from "./pages/JobDetailPage";
import { JobsPage } from "./pages/JobsPage";
import { UploadPage } from "./pages/UploadPage";
import "./styles.css";

function NotFoundPage() {
  return (
    <div className="empty">
      <h1>Page not found</h1>
      <p><Link to="/">Go to the start page</Link></p>
    </div>
  );
}

/** A fresh page instance per job, so navigating from one job to another resets all state. */
function JobRoute() {
  const { jobId } = useParams();
  return <JobDetailPage key={jobId} />;
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <UploadPage /> },
      { path: "/jobs", element: <JobsPage /> },
      { path: "/jobs/:jobId", element: <JobRoute /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>
  </StrictMode>,
);
