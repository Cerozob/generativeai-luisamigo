import Box from "@cloudscape-design/components/box";
import Link from "@cloudscape-design/components/link";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import "./MarkdownContent.css";

// Sin rehype-raw: el HTML que escriba el modelo se muestra como texto y no se interpreta.
const components: Components = {
  a: ({ href, children }) => (
    <Link href={href} external>
      {children}
    </Link>
  ),
  code: ({ className, children }) =>
    // Los bloques de código traen la clase language-*; el código en línea no.
    className ? <code className={className}>{children}</code> : <Box variant="code">{children}</Box>,
};

export function MarkdownContent({ children }: { children: string }) {
  return (
    <div className="markdown-content">
      <Markdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </Markdown>
    </div>
  );
}
