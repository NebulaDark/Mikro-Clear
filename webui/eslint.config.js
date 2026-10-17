import js from "@eslint/js";
import vue from "eslint-plugin-vue";
import globals from "globals";

export default [
  js.configs.recommended,
  ...vue.configs["flat/essential"],
  {
    files: ["src/**/*.{js,vue}", "vite.config.js"],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
  },
];
