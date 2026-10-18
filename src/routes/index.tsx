import { createFileRoute } from "@tanstack/react-router";
import { DownloaderApp } from "@/features/downloads/app";

export const Route = createFileRoute("/")({
  component: Home,
});

function Home() {
  return <DownloaderApp />;
}
