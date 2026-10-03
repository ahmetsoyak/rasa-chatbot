import { UserRound } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import type { HandoverNoticePayload } from "@/lib/payloads";

const labels: Record<string, string> = {
  destination: "Destination",
  origin: "Starting point",
  travel_dates: "Travel dates",
  budget: "Budget",
  sustainability_level: "Sustainability priority",
};

export function HandoverCard({ payload }: { payload: HandoverNoticePayload }) {
  const trip = payload.context?.trip ?? {};
  const details = Object.entries(trip).filter(([, value]) => value !== null && value !== undefined && value !== "");

  return (
    <Card className="w-full border-blue-300 bg-blue-50 dark:border-blue-800 dark:bg-blue-950/40">
      <CardContent className="space-y-3 p-4 text-sm">
        <div className="flex items-start gap-2">
          <UserRound className="mt-0.5 size-4 shrink-0 text-blue-700 dark:text-blue-400" aria-hidden="true" />
          <div>
            <p className="font-semibold">Handover package prepared</p>
            {payload.ticket_id && <p className="text-xs text-muted-foreground">Reference: {payload.ticket_id}</p>}
          </div>
        </div>
        <p>{payload.message ?? "Your trip details are ready for a human travel advisor."}</p>
        <details className="rounded-md border bg-background/60 px-3 py-2">
          <summary className="cursor-pointer font-medium">View advisor handover details</summary>
          <div className="mt-3 space-y-3 border-t pt-3">
            {details.length > 0 && (
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                {details.map(([key, value]) => (
                  <div key={key} className="contents">
                    <dt className="text-muted-foreground">{labels[key] ?? key}</dt>
                    <dd>{String(value)}</dd>
                  </div>
                ))}
              </dl>
            )}
            <p className="text-xs text-muted-foreground">
              {payload.context?.transcript_turns ?? 0} conversation turns and the recommendations shown are included in the package.
            </p>
            {payload.context?.privacy && <p className="text-xs text-muted-foreground">{payload.context.privacy}</p>}
          </div>
        </details>
      </CardContent>
    </Card>
  );
}
