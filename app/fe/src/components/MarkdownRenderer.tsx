import type { ReactElement } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import { MentionChip } from "./MentionChip";

// Split text on @mention patterns, return mixed string/element array
function renderWithMentions(text: string): (string | ReactElement)[] {
  const parts: (string | ReactElement)[] = [];
  const re = /@([\w][\w-]*)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    parts.push(<MentionChip key={match.index} name={match[1]} />);
    last = re.lastIndex;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

// Custom text renderer that highlights @mentions inside paragraphs, list items, etc.
function MentionText({ children }: { children?: React.ReactNode }) {
  if (typeof children === "string") {
    const parts = renderWithMentions(children);
    return parts.length === 1 && typeof parts[0] === "string"
      ? <>{children}</>
      : <>{parts}</>;
  }
  if (Array.isArray(children)) {
    return (
      <>
        {children.map((child, i) =>
          typeof child === "string" ? (
            <span key={i}>{renderWithMentions(child)}</span>
          ) : (
            child
          )
        )}
      </>
    );
  }
  return <>{children}</>;
}

// Override text-containing elements to process @mentions
const mentionComponents = {
  p: ({ children, ...props }: any) => <p {...props}><MentionText>{children}</MentionText></p>,
  li: ({ children, ...props }: any) => <li {...props}><MentionText>{children}</MentionText></li>,
  td: ({ children, ...props }: any) => <td {...props}><MentionText>{children}</MentionText></td>,
  th: ({ children, ...props }: any) => <th {...props}><MentionText>{children}</MentionText></th>,
  strong: ({ children, ...props }: any) => <strong {...props}><MentionText>{children}</MentionText></strong>,
  em: ({ children, ...props }: any) => <em {...props}><MentionText>{children}</MentionText></em>,
};

export function MarkdownRenderer({ content }: { content: string }) {
  // Unescape literal \n \t \r sequences from double-escaped messages
  const unescaped = content
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, "\t")
    .replace(/\\r/g, "\r");

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={mentionComponents}
    >
      {unescaped}
    </ReactMarkdown>
  );
}

// Extract unique @mentions from text
export function extractMentions(text: string): string[] {
  const re = /@([\w][\w-]*)/g;
  const mentions = new Set<string>();
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    mentions.add(match[1]);
  }
  return [...mentions];
}
