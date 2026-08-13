import eslint from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import nextPlugin from "@next/eslint-plugin-next";

export default tseslint.config(
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  { plugins: { "react-hooks": reactHooks }, rules: { ...reactHooks.configs.recommended.rules, "react-hooks/set-state-in-effect": "off" } },
  { plugins: { "@next/next": nextPlugin }, rules: nextPlugin.configs.recommended.rules },
  {
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          destructuredArrayIgnorePattern: "^_",
          ignoreRestSiblings: true,
        },
      ],
    },
  },
  { ignores: [".next/", "out/", "node_modules/", "src/components/ui/", "src/components/magicui/"] }
);
