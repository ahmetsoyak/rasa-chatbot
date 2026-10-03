/** Colour, icon and wording for each emission band (see components/BandBadge.tsx). */
import { AlertTriangle, Gauge, Leaf } from "lucide-react";
import type { CarbonBand } from "@/lib/payloads";

export const BAND_META: Record<CarbonBand, { label: string; text: string; surface: string; Icon: typeof Leaf }> = {
  green: {
    label: "Low emissions",
    text: "text-emerald-800 dark:text-emerald-300",
    surface: "border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/40",
    Icon: Leaf,
  },
  amber: {
    label: "Moderate emissions",
    text: "text-amber-800 dark:text-amber-300",
    surface: "border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/40",
    Icon: Gauge,
  },
  red: {
    label: "High emissions",
    text: "text-red-800 dark:text-red-300",
    surface: "border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950/40",
    Icon: AlertTriangle,
  },
};
