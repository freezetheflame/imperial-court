import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { useEventStream } from "./lib/useEventStream";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { refetchOnWindowFocus: false, staleTime: 10_000 },
  },
});

// small bridge component so useEventStream lives under the provider
function EventBridge() {
  useEventStream();
  return null;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <EventBridge />
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>
);
