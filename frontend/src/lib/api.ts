// Base URL of the FastAPI backend. Set VITE_API_BASE in the root .env to override.
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'
