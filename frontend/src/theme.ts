import { useEffect } from "react";

// Day (light) is the default; the user's choice is persisted by the caller.
export type Theme = "light" | "dark";

export function useTheme(theme: Theme): Theme {
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  return theme;
}

export interface ChartPalette {
  bg: string;
  text: string;
  grid: string;
  border: string;
  level: string;
  crosshair: string;
}

export const CHART_THEME: Record<Theme, ChartPalette> = {
  light: { bg: "#ffffff", text: "#434651", grid: "#f0f3fa", border: "#e0e3eb", level: "#b2b5be", crosshair: "#9598a1" },
  dark: { bg: "#0f1218", text: "#a7adbb", grid: "#1a1f29", border: "#262b36", level: "#4b5263", crosshair: "#5d6575" },
};
