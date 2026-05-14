import tsParser from '@typescript-eslint/parser'

export default [
  {
    ignores: ['.next/**', 'node_modules/**', '.pnpm-store/**']
  },
  {
    files: ['**/*.{js,mjs,cjs,ts,jsx,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        ecmaFeatures: {
          jsx: true
        }
      }
    },
    rules: {}
  }
];
