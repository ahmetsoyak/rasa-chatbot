import type { ReactNode } from "react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { CarbonScoreCard } from "@/components/CarbonScoreCard";
import { ExperienceList } from "@/components/ExperienceList";
import { HotelCarousel } from "@/components/HotelCarousel";
import { OffsetInfo } from "@/components/OffsetInfo";
import { TransportOptions } from "@/components/TransportOptions";
import { WeatherCard } from "@/components/WeatherCard";
import { HandoverCard } from "@/components/HandoverCard";
import { DatePicker } from "@/components/DatePicker";
import {
  payloadIs,
  type CarbonScoreCardPayload,
  type ExperienceListPayload,
  type HotelCarouselPayload,
  type HandoverNoticePayload,
  type OffsetInfoPayload,
  type TransportOptionsPayload,
  type WeatherCardPayload,
} from "@/lib/payloads";
import { SHARE_LOCATION_PAYLOAD, type ChatMessage } from "@/hooks/useChat";
import { Bot, MapPin, TriangleAlert, User } from "lucide-react";

interface MessageBubbleProps {
  message: ChatMessage;
  onButtonClick: (payload: string, title: string) => void;
  disabled: boolean;
  /** Interactive prompts (the date picker) only work on the newest message. */
  isLatest?: boolean;
}

/** Pick the rich component for a custom payload. Unknown types render nothing. */
const CARD_LABELS: Record<string, string> = {
  carbon_card: "Carbon comparison",
  transport_options: "Getting around",
  experience_list: "Things to do",
  weather_card: "Weather forecast",
  offset_info: "Carbon offsets",
  handover_notice: "Human advisor handover",
};

function renderCustom(custom: Record<string, unknown>): ReactNode {
  if (payloadIs<CarbonScoreCardPayload>(custom, "carbon_card")) return <CarbonScoreCard payload={custom} />;
  if (payloadIs<HotelCarouselPayload>(custom, "hotel_carousel")) return <HotelCarousel payload={custom} />;
  if (payloadIs<TransportOptionsPayload>(custom, "transport_options")) return <TransportOptions payload={custom} />;
  if (payloadIs<ExperienceListPayload>(custom, "experience_list")) return <ExperienceList payload={custom} />;
  if (payloadIs<WeatherCardPayload>(custom, "weather_card")) return <WeatherCard payload={custom} />;
  if (payloadIs<OffsetInfoPayload>(custom, "offset_info")) return <OffsetInfo payload={custom} />;
  if (payloadIs<HandoverNoticePayload>(custom, "handover_notice")) return <HandoverCard payload={custom} />;
  return null;
}

export function MessageBubble({ message, onButtonClick, disabled, isLatest = false }: MessageBubbleProps) {
  const isUser = message.sender === "user";

  if (message.sender === "system-error") {
    return (
      <div className="flex items-start gap-2 self-start" role="alert">
        <Avatar className="size-8 shrink-0" aria-hidden="true">
          <AvatarFallback className="bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300">
            <TriangleAlert className="size-4" />
          </AvatarFallback>
        </Avatar>
        <Card className="max-w-[85%] border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950/40">
          <CardContent className="p-3 text-sm text-red-800 dark:text-red-300">{message.text}</CardContent>
        </Card>
      </div>
    );
  }

  if (message.companion) return null;
  if (payloadIs(message.custom, "date_picker")) {
    if (!isLatest) return null;
    return (
      <div className="w-full pl-10">
        <DatePicker disabled={disabled} onSubmit={onButtonClick} />
      </div>
    );
  }
  const customContent = message.custom ? renderCustom(message.custom) : null;
  if (!message.text && !customContent && !message.buttons?.length) return null;

  return (
    <div className={`flex items-start gap-2 ${isUser ? "flex-row-reverse self-end" : "self-start"} w-full`}>
      <Avatar className="size-8 shrink-0" aria-hidden="true">
        <AvatarFallback
          className={isUser ? "bg-primary text-primary-foreground" : "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"}
        >
          {isUser ? <User className="size-4" /> : <Bot className="size-4" />}
        </AvatarFallback>
      </Avatar>

      <div className={`flex min-w-0 max-w-[85%] flex-col gap-2 ${isUser ? "items-end" : "items-start"}`}>
        {message.text && (
          <Card className={`gap-0 py-0 ${isUser ? "bg-primary text-primary-foreground" : ""}`}>
            <CardContent className="p-3 text-sm whitespace-pre-wrap">
              <span className="sr-only">{isUser ? "You said: " : "Advisor: "}</span>
              {message.text}
            </CardContent>
          </Card>
        )}

        {customContent &&
          (CARD_LABELS[String(message.custom?.type)] ? (
            <div role="group" className="w-full" aria-label={`Advisor: ${CARD_LABELS[String(message.custom?.type)]}`}>
              {customContent}
            </div>
          ) : (
            customContent
          ))}

        {message.buttons && message.buttons.length > 0 && (
          <div className="flex flex-wrap gap-2" role="group" aria-label="Suggested replies">
            {message.buttons.map((btn, i) => (
              <Button
                key={`${btn.payload}-${i}`}
                variant="outline"
                size="sm"
                disabled={disabled}
                onClick={() => onButtonClick(btn.payload, btn.title)}
              >
                {btn.payload === SHARE_LOCATION_PAYLOAD && <MapPin aria-hidden="true" />}
                {btn.title}
              </Button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
