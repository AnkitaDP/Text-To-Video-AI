import {
  AbsoluteFill,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
export interface WordCaption {
  word: string;
  startMs: number;
  endMs: number;
}
interface CaptionOverlayProps {
  words: WordCaption[];
  wordsPerPage?: number;
  fontSize?: number;
  color?: string;
  highlightColor?: string;
  backgroundColor?: string;
  fontFamily?: string;
}
interface CaptionPage {
  words: WordCaption[];
  startMs: number;
  endMs: number;
}
function buildPages(words: WordCaption[], wordsPerPage: number): CaptionPage[] {
  const pages: CaptionPage[] = [];
  for (let i = 0; i < words.length; i += wordsPerPage) {
    const pageWords = words.slice(i, i + wordsPerPage);
    if (pageWords.length === 0) {
      continue;
    }
    pages.push({
      words: pageWords,
      startMs: pageWords[0].startMs,
      endMs: pageWords[pageWords.length - 1].endMs,
    });
  }
  return pages;
}
const PageRenderer: React.FC<{
  page: CaptionPage;
  fontSize: number;
  color: string;
  highlightColor: string;
  backgroundColor: string;
  fontFamily: string;
}> = ({
  page,
  fontSize,
  color,
  highlightColor,
  backgroundColor: _backgroundColor,
  fontFamily,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentMs = page.startMs + (frame / fps) * 1000;
  const entrance = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 120 },
  });
  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
        paddingLeft: 70,
        paddingRight: 70,
        paddingBottom: 180,
        pointerEvents: "none",
      }}
    >
      {" "}
      <div
        style={{
          opacity: entrance,
          transform: `translateY(${interpolate(entrance, [0, 1], [30, 0])}px)`,
          maxWidth: 880,
          textAlign: "center",
          boxSizing: "border-box",
        }}
      >
        {" "}
        <span
          style={{
            fontSize,
            fontWeight: 700,
            fontFamily,
            lineHeight: 1.3,
            whiteSpace: "pre-wrap",
            wordSpacing: "-4px",
          }}
        >
          {" "}
          {page.words.map((w, i) => {
            const isActive = w.startMs <= currentMs && w.endMs > currentMs;
            const isPast = w.endMs <= currentMs;
            return (
              <span
                key={`${w.startMs}-${i}`}
                style={{
                  color: isActive
                    ? highlightColor
                    : isPast
                      ? color
                      : `${color}99`,
                  textShadow: ` 2px 2px 0 #000, -2px -2px 0 #000, 2px -2px 0 #000, -2px 2px 0 #000, 0 3px 8px rgba(0, 0, 0, 0.9) `,
                }}
              >
                {" "}
                {w.word} {i < page.words.length - 1 ? " " : ""}{" "}
              </span>
            );
          })}{" "}
        </span>{" "}
      </div>{" "}
    </AbsoluteFill>
  );
};
export const CaptionOverlay: React.FC<CaptionOverlayProps> = ({
  words,
  wordsPerPage = 4,
  fontSize = 52,
  color = "#F8FAFC",
  highlightColor = "#22D3EE",
  backgroundColor,
  fontFamily = "Arial, sans-serif",
}) => {
  const { fps } = useVideoConfig();
  const pages = buildPages(words, wordsPerPage);
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {" "}
      {pages.map((page, i) => {
        const fromFrame = Math.round((page.startMs / 1000) * fps);
        const nextStart = pages[i + 1]?.startMs ?? page.endMs + 500;
        const duration = Math.max(
          1,
          Math.round(((nextStart - page.startMs) / 1000) * fps),
        );
        return (
          <Sequence key={i} from={fromFrame} durationInFrames={duration}>
            {" "}
            <PageRenderer
              page={page}
              fontSize={fontSize}
              color={color}
              highlightColor={highlightColor}
              backgroundColor={backgroundColor ?? "transparent"}
              fontFamily={fontFamily}
            />{" "}
          </Sequence>
        );
      })}{" "}
    </AbsoluteFill>
  );
};
