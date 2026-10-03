import { Landmark, Users } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { asArray, type ExperienceListPayload } from "@/lib/payloads";

export function ExperienceList({ payload }: { payload: ExperienceListPayload }) {
  const items = asArray(payload.items);
  if (items.length === 0) return null;

  return (
    <Card className="w-full max-w-xl">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Landmark className="size-4" aria-hidden="true" />
          Things to do{payload.destination ? ` in ${payload.destination}` : ""}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-3 text-sm">
          {items.map((item, i) => (
            <li key={`${item.name}-${i}`} className="space-y-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-medium">{item.name}</span>
                {item.supports_local_community && (
                  <Badge variant="secondary">
                    <Users aria-hidden="true" /> Community-run
                  </Badge>
                )}
                {item.wheelchair === "yes" && <Badge variant="outline">Wheelchair accessible</Badge>}
              </div>
              {item.description && <p className="text-xs text-muted-foreground">{item.description}</p>}
              <p className="text-[11px] text-muted-foreground">
                {[item.kind, item.data_source].filter(Boolean).join(" · ")}
              </p>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
