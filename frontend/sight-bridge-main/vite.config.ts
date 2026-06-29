import { defineConfig } from "@lovable.dev/vite-tanstack-config";

export default defineConfig({
  tanstackStart: {
    server: { entry: "server" },
  },
  nitro:
    process.env.NODE_ENV === "production" || process.env.DOCKER_BUILD
      ? { preset: "node-server" }
      : undefined,
});
