/** Configuración de runtime: el despliegue la publica como /config.json junto al frontend. */
export interface RuntimeConfig {
  region: string;
  userPoolId: string;
  userPoolClientId: string;
  cognitoDomain: string;
  /** Ruta del endpoint del agente. CloudFront la reenvía a AgentCore Runtime (mismo origen, sin CORS). */
  agentUrl: string;
}

const REQUIRED_KEYS: (keyof RuntimeConfig)[] = ["region", "userPoolId", "userPoolClientId", "cognitoDomain", "agentUrl"];

export async function loadConfig(): Promise<RuntimeConfig> {
  const response = await fetch("/config.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`No se pudo cargar config.json (${response.status})`);
  }
  const raw = (await response.json()) as Record<string, unknown>;
  for (const key of REQUIRED_KEYS) {
    if (typeof raw[key] !== "string" || raw[key] === "") {
      throw new Error(`config.json: falta el valor '${key}'`);
    }
  }
  return raw as unknown as RuntimeConfig;
}
