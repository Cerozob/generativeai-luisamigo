import Avatar from "@cloudscape-design/chat-components/avatar";
import ChatBubble from "@cloudscape-design/chat-components/chat-bubble";
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { MarkdownContent } from "./MarkdownContent";

export interface Mensaje {
  id: string;
  rol: "usuario" | "agente";
  texto: string;
  herramientas?: string[];
  error?: boolean;
}

// Nombre amigable de cada herramienta del agente (agent/herramientas.py).
const HERRAMIENTAS: Record<string, string> = {
  buscar_mundial: "Base de conocimiento",
  buscar_catalogo: "Catálogo",
  resumen_album: "Resumen del álbum",
  listar_laminas: "Listar láminas",
  consultar_lamina: "Consultar lámina",
  agregar_lamina: "Agregar lámina",
  actualizar_lamina: "Actualizar lámina",
  eliminar_lamina: "Eliminar lámina",
};

export function ChatMessage({ mensaje }: { mensaje: Mensaje }) {
  const esUsuario = mensaje.rol === "usuario";
  return (
    <ChatBubble
      type={esUsuario ? "outgoing" : "incoming"}
      ariaLabel={esUsuario ? "Tu mensaje" : "Respuesta de Parcero"}
      avatar={
        esUsuario ? (
          <Avatar ariaLabel="Tú" iconName="user-profile" />
        ) : (
          <Avatar ariaLabel="Parcero" color="gen-ai" iconName="gen-ai" />
        )
      }
    >
      <SpaceBetween size="xs">
        {mensaje.error && <StatusIndicator type="error">Error del agente</StatusIndicator>}
        {/* El agente responde en Markdown; el texto del usuario se muestra tal cual lo escribió. */}
        {esUsuario ? (
          <div style={{ whiteSpace: "pre-wrap" }}>{mensaje.texto}</div>
        ) : (
          <MarkdownContent>{mensaje.texto}</MarkdownContent>
        )}
        {(mensaje.herramientas?.length ?? 0) > 0 && (
          <SpaceBetween size="xxs" direction="horizontal">
            {mensaje.herramientas!.map((herramienta) => (
              <Badge key={herramienta} color="grey">
                {HERRAMIENTAS[herramienta] ?? herramienta}
              </Badge>
            ))}
          </SpaceBetween>
        )}
      </SpaceBetween>
    </ChatBubble>
  );
}

export function Pensando() {
  return (
    <ChatBubble
      type="incoming"
      ariaLabel="Parcero está respondiendo"
      showLoadingBar
      avatar={<Avatar ariaLabel="Parcero" color="gen-ai" iconName="gen-ai" loading />}
    >
      <Box color="text-status-inactive">Parcero está pensando…</Box>
    </ChatBubble>
  );
}
