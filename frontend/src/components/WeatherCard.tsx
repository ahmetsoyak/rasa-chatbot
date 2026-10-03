import { CloudSun } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { asArray, fmt, type WeatherCardPayload } from "@/lib/payloads";

function dayLabel(iso?: string): string {
  if (!iso) return "";
  const d = new Date(`${iso}T12:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

export function WeatherCard({ payload }: { payload: WeatherCardPayload }) {
  const days = asArray(payload.days);

  return (
    <Card className="w-full max-w-md">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <CloudSun className="size-4" aria-hidden="true" />
          Weather{payload.destination ? ` in ${payload.destination}` : ""}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {payload.current && (
          <p>
            <span className="text-2xl font-semibold">{fmt(payload.current.temp)}°C</span>{" "}
            <span className="text-muted-foreground">now, {payload.current.summary}</span>
          </p>
        )}
        {days.length > 0 && (
          <ul className="grid grid-cols-3 gap-2">
            {days.map((d) => (
              <li key={d.date} className="rounded-md bg-muted/60 p-2 text-xs">
                <span className="block font-medium">{dayLabel(d.date)}</span>
                <span className="block">{fmt(d.t_min)}–{fmt(d.t_max)}°C</span>
                <span className="block text-muted-foreground">{d.summary}</span>
                {typeof d.rain_chance === "number" && (
                  <span className="block text-muted-foreground">{d.rain_chance}% rain</span>
                )}
              </li>
            ))}
          </ul>
        )}
        {payload.tip && <p>{payload.tip}</p>}
        <p className="text-xs text-muted-foreground">
          Next 3 days, not your travel dates. Source: {payload.source ?? "Open-Meteo"}.
        </p>
      </CardContent>
    </Card>
  );
}
