export type Estado = "falta" | "tengo" | "repetida";

export interface Lamina {
  codigo: string;
  jugador: string;
  pais: string;
  grupo: string;
  numero: number;
  estado: Estado;
  repetidas: number;
  notas?: string;
}

export interface Album {
  usuario: string;
  faltan: number;
  repetidas: number;
  copiasParaCambiar: number;
  laminas: Lamina[];
}

export interface Ingesta {
  id: string;
  estado: "STARTING" | "IN_PROGRESS" | "COMPLETE" | "FAILED" | "STOPPING" | "STOPPED";
  inicio: string;
  fin: string;
  estadisticas: Record<string, number>;
  errores: string[];
}

export interface EstadoKb {
  fuente: string;
  ultimaIngesta: Ingesta | null;
  aviso?: string;
}

export interface UrlSubida {
  url: string;
  clave: string;
  tipo: string;
}
