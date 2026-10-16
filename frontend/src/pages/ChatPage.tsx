import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Flashbar, { type FlashbarProps } from "@cloudscape-design/components/flashbar";
import Header from "@cloudscape-design/components/header";
import PromptInput from "@cloudscape-design/components/prompt-input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useEffect, useRef, useState } from "react";
import { nuevaSesion } from "../api/agente";
import { useAgente } from "../api/context";
import { ChatMessage, Pensando, type Mensaje } from "../components/ChatMessage";

const MAX_LENGTH = 4000;
const MENSAJES_KEY = "parcero-mensajes";

const EJEMPLOS = [
  "¿Quién ganó la final del Mundial 2026 y con qué marcador?",
  "¿Cuántas láminas me faltan de Colombia?",
  "Me salió Julián Álvarez",
  "¿Qué repetidas tengo para cambiar?",
];

function leerMensajes(): Mensaje[] {
  try {
    return JSON.parse(sessionStorage.getItem(MENSAJES_KEY) ?? "[]");
  } catch {
    return [];
  }
}

export default function ChatPage() {
  const agente = useAgente();
  // La memoria de la conversación vive en AgentCore Memory; aquí solo se guarda lo que se muestra.
  const [mensajes, setMensajes] = useState<Mensaje[]>(leerMensajes);
  const [prompt, setPrompt] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [flash, setFlash] = useState<FlashbarProps.MessageDefinition[]>([]);
  const finRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    sessionStorage.setItem(MENSAJES_KEY, JSON.stringify(mensajes));
    finRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [mensajes, enviando]);

  const enviar = async (texto: string) => {
    const contenido = texto.trim();
    if (!contenido || enviando) return;
    if (contenido.length > MAX_LENGTH) {
      setFlash([{ type: "error", content: `El mensaje no puede superar ${MAX_LENGTH} caracteres.`, id: "largo" }]);
      return;
    }
    setMensajes((actuales) => [...actuales, { id: `u-${Date.now()}`, rol: "usuario", texto: contenido }]);
    setPrompt("");
    setFlash([]);
    setEnviando(true);
    try {
      const { respuesta, herramientas } = await agente.conversar(contenido);
      setMensajes((actuales) => [...actuales, { id: `a-${Date.now()}`, rol: "agente", texto: respuesta, herramientas }]);
    } catch (error) {
      const texto = `No pude responder: ${(error as Error).message}`;
      setMensajes((actuales) => [...actuales, { id: `e-${Date.now()}`, rol: "agente", texto, error: true }]);
    } finally {
      setEnviando(false);
    }
  };

  const nueva = () => {
    nuevaSesion();
    setMensajes([]);
  };

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Pregúntale por el Mundial 2026 o cuéntale qué láminas te salieron."
          actions={
            <Button iconName="add-plus" onClick={nueva} disabled={enviando}>
              Nueva conversación
            </Button>
          }
        >
          Conversa con Parcero
        </Header>
      }
    >
      <SpaceBetween size="m">
        <Flashbar items={flash} />
        <Container
          footer={
            <PromptInput
              value={prompt}
              onChange={({ detail }) => setPrompt(detail.value)}
              onAction={() => void enviar(prompt)}
              placeholder="Escribe tu mensaje"
              actionButtonIconName="send"
              actionButtonAriaLabel="Enviar"
              disableActionButton={enviando || prompt.trim() === ""}
              minRows={2}
              maxRows={8}
            />
          }
        >
          <div style={{ height: "60vh", overflowY: "auto" }}>
            <SpaceBetween size="m">
              {mensajes.length === 0 && !enviando && (
                <Box textAlign="center" padding="xxl">
                  <SpaceBetween size="s" alignItems="center">
                    <Box color="text-status-inactive">Prueba con uno de estos mensajes:</Box>
                    {EJEMPLOS.map((ejemplo) => (
                      <Button key={ejemplo} variant="inline-link" onClick={() => void enviar(ejemplo)}>
                        {ejemplo}
                      </Button>
                    ))}
                  </SpaceBetween>
                </Box>
              )}
              {mensajes.map((mensaje) => (
                <ChatMessage key={mensaje.id} mensaje={mensaje} />
              ))}
              {enviando && <Pensando />}
              <div ref={finRef} />
            </SpaceBetween>
          </div>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
