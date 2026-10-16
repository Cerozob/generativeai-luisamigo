import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FileUpload from "@cloudscape-design/components/file-upload";
import Flashbar, { type FlashbarProps } from "@cloudscape-design/components/flashbar";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import KeyValuePairs from "@cloudscape-design/components/key-value-pairs";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator, { type StatusIndicatorProps } from "@cloudscape-design/components/status-indicator";
import { useCallback, useEffect, useState } from "react";
import { subirAS3 } from "../api/agente";
import { useAgente } from "../api/context";
import type { EstadoKb, Ingesta, UrlSubida } from "../api/types";

// Formatos y tamaño máximo que admite la base de conocimiento; el agente vuelve a validarlos.
const ACEPTADOS = ".pdf,.txt,.md,.html,.htm,.csv,.doc,.docx,.xls,.xlsx";
const MAX_BYTES = 50 * 1024 * 1024;
const EN_CURSO = ["STARTING", "IN_PROGRESS", "STOPPING"];

const ESTADOS: Record<Ingesta["estado"], { texto: string; tipo: StatusIndicatorProps.Type }> = {
  STARTING: { texto: "Iniciando", tipo: "pending" },
  IN_PROGRESS: { texto: "En curso", tipo: "in-progress" },
  COMPLETE: { texto: "Completa", tipo: "success" },
  FAILED: { texto: "Falló", tipo: "error" },
  STOPPING: { texto: "Deteniéndose", tipo: "pending" },
  STOPPED: { texto: "Detenida", tipo: "stopped" },
};

const fecha = (iso: string) => (iso ? new Date(iso).toLocaleString("es-CO") : "-");

export default function DocumentosPage() {
  const agente = useAgente();
  const [archivos, setArchivos] = useState<File[]>([]);
  const [subiendo, setSubiendo] = useState(false);
  const [kb, setKb] = useState<EstadoKb | null>(null);
  const [sincronizando, setSincronizando] = useState(false);
  const [flash, setFlash] = useState<FlashbarProps.MessageDefinition[]>([]);

  const avisar = (type: FlashbarProps.Type, content: string) => {
    const id = `${Date.now()}-${Math.random()}`;
    const quitar = () => setFlash((items) => items.filter((i) => i.id !== id));
    setFlash((actuales) => [{ id, type, content, dismissible: true, onDismiss: quitar }, ...actuales]);
  };

  const consultarKb = useCallback(async () => {
    try {
      setKb(await agente.accion<EstadoKb>("estado_kb"));
    } catch (error) {
      avisar("error", `No se pudo leer el estado de la base: ${(error as Error).message}`);
    }
  }, [agente]);

  useEffect(() => {
    void consultarKb();
  }, [consultarKb]);

  // Mientras haya una ingesta en curso, se consulta su estado cada 10 segundos.
  const enCurso = EN_CURSO.includes(kb?.ultimaIngesta?.estado ?? "");
  useEffect(() => {
    if (!enCurso) return;
    const intervalo = setInterval(() => void consultarKb(), 10_000);
    return () => clearInterval(intervalo);
  }, [enCurso, consultarKb]);

  const demasiadoGrandes = archivos.filter((archivo) => archivo.size > MAX_BYTES);

  const subir = async () => {
    setSubiendo(true);
    for (const archivo of archivos) {
      try {
        const destino = await agente.accion<UrlSubida>("subir_documento", {
          nombre: archivo.name,
          tipo: archivo.type || "application/octet-stream",
          tamano: archivo.size,
        });
        await subirAS3(destino.url, destino.tipo, archivo);
        avisar("success", `${archivo.name} quedó en S3 (${destino.clave}).`);
      } catch (error) {
        avisar("error", `${archivo.name}: ${(error as Error).message}`);
      }
    }
    setArchivos([]);
    setSubiendo(false);
  };

  const sincronizar = async () => {
    setSincronizando(true);
    try {
      const estado = await agente.accion<EstadoKb>("sincronizar_kb");
      setKb(estado);
      avisar(estado.aviso ? "warning" : "info", estado.aviso ?? "Sincronización iniciada.");
    } catch (error) {
      avisar("error", `No se pudo sincronizar: ${(error as Error).message}`);
    } finally {
      setSincronizando(false);
    }
  };

  const ingesta = kb?.ultimaIngesta;
  const stats = ingesta?.estadisticas ?? {};

  return (
    <ContentLayout
      header={
        <Header variant="h1" description="Sube documentos a S3 y sincroniza la base de conocimiento administrada.">
          Documentos
        </Header>
      }
    >
      <SpaceBetween size="l">
        <Flashbar items={flash} stackItems />
        <Container header={<Header variant="h2">1. Subir documentos</Header>}>
          <SpaceBetween size="m">
            <FormField
              label="Archivos"
              description="PDF, Word, Excel, CSV, HTML, Markdown o texto, de hasta 50 MB cada uno."
              errorText={
                demasiadoGrandes.length > 0 ? `Superan 50 MB: ${demasiadoGrandes.map((a) => a.name).join(", ")}` : undefined
              }
            >
              <FileUpload
                multiple
                value={archivos}
                onChange={({ detail }) => setArchivos(detail.value)}
                accept={ACEPTADOS}
                showFileSize
                i18nStrings={{
                  uploadButtonText: (multiple) => (multiple ? "Elegir archivos" : "Elegir archivo"),
                  dropzoneText: (multiple) => (multiple ? "Suelta los archivos aquí" : "Suelta el archivo aquí"),
                  removeFileAriaLabel: (index) => `Quitar el archivo ${index + 1}`,
                  limitShowFewer: "Mostrar menos",
                  limitShowMore: "Mostrar más",
                  errorIconAriaLabel: "Error",
                }}
              />
            </FormField>
            <Button
              variant="primary"
              onClick={() => void subir()}
              loading={subiendo}
              disabled={archivos.length === 0 || demasiadoGrandes.length > 0}
            >
              Subir
            </Button>
          </SpaceBetween>
        </Container>
        <Container
          header={
            <Header
              variant="h2"
              description="La base solo responde con lo que ya ingirió: después de subir archivos, sincroniza."
              actions={
                <SpaceBetween size="xs" direction="horizontal">
                  <Button iconName="refresh" ariaLabel="Actualizar estado" onClick={() => void consultarKb()} />
                  <Button
                    variant="primary"
                    onClick={() => void sincronizar()}
                    loading={sincronizando}
                    disabled={enCurso || kb?.fuente !== "AVAILABLE"}
                  >
                    Sincronizar base de conocimiento
                  </Button>
                </SpaceBetween>
              }
            >
              2. Sincronizar
            </Header>
          }
        >
          <KeyValuePairs
            columns={4}
            items={[
              { label: "Fuente de datos", value: kb?.fuente ?? "-" },
              {
                label: "Última ingesta",
                value: ingesta ? (
                  <StatusIndicator type={ESTADOS[ingesta.estado].tipo}>{ESTADOS[ingesta.estado].texto}</StatusIndicator>
                ) : (
                  "Ninguna"
                ),
              },
              { label: "Inicio", value: fecha(ingesta?.inicio ?? "") },
              { label: "Última actualización", value: fecha(ingesta?.fin ?? "") },
              { label: "Documentos encontrados", value: stats.numberOfDocumentsScanned ?? "-" },
              { label: "Nuevos", value: stats.numberOfNewDocumentsIndexed ?? "-" },
              { label: "Modificados", value: stats.numberOfModifiedDocumentsIndexed ?? "-" },
              { label: "Con error", value: stats.numberOfDocumentsFailed ?? "-" },
            ]}
          />
          {(ingesta?.errores.length ?? 0) > 0 && (
            <Box margin={{ top: "m" }} color="text-status-error">
              {ingesta!.errores.join(" · ")}
            </Box>
          )}
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
