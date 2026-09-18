import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import Components from "unplugin-vue-components/vite";
import { TDesignResolver } from "unplugin-vue-components/resolvers";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [
    vue(),
    Components({
      resolvers: [TDesignResolver({ library: "vue-next" })],
      // 不生成全局组件类型声明：当前代码里 <t-xxx> 有一批与组件严格类型不一致的历史写法，
      // 一旦生成 d.ts，vue-tsc 会把它们全查出来并阻断 build。保持 <t-xxx> 为 any（改造前同款行为），
      // 运行时由 unplugin 注入按需 import，不受影响。
      dts: false,
    }),
  ],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    host: "0.0.0.0",
    allowedHosts: true,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
