import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Flashbar from "@cloudscape-design/components/flashbar";
import Header from "@cloudscape-design/components/header";
import SegmentedControl from "@cloudscape-design/components/segmented-control";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import TextFilter from "@cloudscape-design/components/text-filter";
import { useCallback, useEffect, useState } from "react";
import { useAgente } from "../api/context";
import type { Album, Estado } from "../api/types";

const ETIQUETAS: Record<Estado, { texto: string; tipo: "warning" | "success" | "info" }> = {
  falta: { texto: "Falta", tipo: "warning" },
  tengo: { texto: "Tengo", tipo: "success" },
  repetida: { texto: "Repetida", tipo: "info" },
};

const sinTildes = (texto: string) => texto.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

export default function AlbumPage() {
  const agente = useAgente();
  const [album, setAlbum] = useState<Album | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState("");
  const [estado, setEstado] = useState<"todas" | Estado>("todas");
  const [filtro, setFiltro] = useState("");

  const cargar = useCallback(async () => {
    setCargando(true);
    setError("");
    try {
      setAlbum(await agente.accion<Album>("album"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCargando(false);
    }
  }, [agente]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  const buscado = sinTildes(filtro.trim());
  const laminas = (album?.laminas ?? []).filter(
    (l) =>
      (estado === "todas" || l.estado === estado) &&
      (!buscado || [l.codigo, l.jugador, l.pais].some((campo) => sinTildes(campo).includes(buscado))),
  );

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Tu tracker en DynamoDB. Cuando Parcero registra una lámina, actualiza esta vista."
          actions={
            <Button iconName="refresh" onClick={() => void cargar()} loading={cargando}>
              Actualizar
            </Button>
          }
        >
          Mi álbum{album ? ` (${album.usuario})` : ""}
        </Header>
      }
    >
      <SpaceBetween size="l">
        {error && <Flashbar items={[{ type: "error", content: error, id: "error" }]} />}
        <Container>
          <ColumnLayout columns={3} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">Me faltan</Box>
              <Box variant="awsui-value-large">{album?.faltan ?? "-"}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Láminas repetidas</Box>
              <Box variant="awsui-value-large">{album?.repetidas ?? "-"}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Copias para cambiar</Box>
              <Box variant="awsui-value-large">{album?.copiasParaCambiar ?? "-"}</Box>
            </div>
          </ColumnLayout>
        </Container>
        <Table
          variant="container"
          stickyHeader
          loading={cargando && !album}
          loadingText="Cargando el álbum"
          items={laminas}
          trackBy="codigo"
          header={<Header counter={`(${laminas.length})`}>Láminas registradas</Header>}
          filter={
            <SpaceBetween size="s" direction="horizontal">
              <TextFilter
                filteringText={filtro}
                filteringPlaceholder="Código, jugador o país"
                onChange={({ detail }) => setFiltro(detail.filteringText)}
              />
              <SegmentedControl
                selectedId={estado}
                onChange={({ detail }) => setEstado(detail.selectedId as typeof estado)}
                options={[
                  { id: "todas", text: "Todas" },
                  { id: "falta", text: "Faltan" },
                  { id: "repetida", text: "Repetidas" },
                  { id: "tengo", text: "Tengo" },
                ]}
              />
            </SpaceBetween>
          }
          columnDefinitions={[
            { id: "codigo", header: "Código", cell: (l) => l.codigo },
            { id: "jugador", header: "Jugador", cell: (l) => l.jugador },
            { id: "pais", header: "País", cell: (l) => l.pais },
            {
              id: "estado",
              header: "Estado",
              cell: (l) => <StatusIndicator type={ETIQUETAS[l.estado].tipo}>{ETIQUETAS[l.estado].texto}</StatusIndicator>,
            },
            { id: "repetidas", header: "Copias", cell: (l) => (l.repetidas > 0 ? l.repetidas : "") },
            { id: "notas", header: "Notas", cell: (l) => l.notas ?? "" },
          ]}
          empty={<Box textAlign="center">No hay láminas con ese filtro.</Box>}
        />
      </SpaceBetween>
    </ContentLayout>
  );
}
