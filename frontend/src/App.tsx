// App — route wiring for the imperial court.

import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { MemorialsPage } from "./pages/MemorialsPage";
import { EdictsPage } from "./pages/EdictsPage";
import { CensoratePage } from "./pages/CensoratePage";
import { CourtroomPage } from "./pages/CourtroomPage";
import { PostsPage } from "./pages/PostsPage";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<MemorialsPage />} />
        <Route path="/edicts" element={<EdictsPage />} />
        <Route path="/censorate" element={<CensoratePage />} />
        <Route path="/courtroom" element={<CourtroomPage />} />
        <Route path="/posts" element={<PostsPage />} />
      </Routes>
    </Layout>
  );
}
