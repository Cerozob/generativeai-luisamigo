/**
 * Cliente del agente en AgentCore Runtime. Todo pasa por un solo endpoint (POST /invocations), que
 * responde JSON:
 * - {prompt}: un turno de conversación.
 * - {accion}: botones del frontend (álbum, subir documento, sincronizar la base).
 *
 * Con un authorizer JWT, AgentCore no se llama con el SDK de AWS sino con HTTPS y el access token de
 * Cognito en el header Authorization.
 */

export interface RespuestaAgente {
  respuesta: string;
  herramientas: string[];
}

export class AgenteError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const SESION_KEY = "parcero-sesion";

/** AgentCore exige un runtimeSessionId de al menos 33 caracteres; un UUID tiene 36. */
export function sesionActual(): string {
  let sesion = sessionStorage.getItem(SESION_KEY);
  if (!sesion) {
    sesion = crypto.randomUUID();
    sessionStorage.setItem(SESION_KEY, sesion);
  }
  return sesion;
}

export function nuevaSesion(): string {
  sessionStorage.removeItem(SESION_KEY);
  return sesionActual();
}

export class AgenteClient {
  private readonly url: string;
  private readonly getToken: () => string | undefined;

  constructor(url: string, getToken: () => string | undefined) {
    this.url = url;
    this.getToken = getToken;
  }

  private async post(payload: object): Promise<Response> {
    let response: Response;
    try {
      response = await fetch(this.url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          Authorization: `Bearer ${this.getToken() ?? ""}`,
          "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": sesionActual(),
        },
        body: JSON.stringify(payload),
      });
    } catch {
      throw new AgenteError(0, "No hubo respuesta del agente.");
    }
    if (!response.ok) {
      const cuerpo = await response.text();
      let mensaje = cuerpo;
      try {
        mensaje = JSON.parse(cuerpo).message ?? cuerpo;
      } catch {
        // El cuerpo no es JSON.
      }
      if (response.status === 401 || response.status === 403) mensaje = `Sesión no autorizada: ${mensaje}`;
      throw new AgenteError(response.status, mensaje || `Error ${response.status}`);
    }
    return response;
  }

  /** Un turno de conversación: el agente responde cuando termina (puede usar varias herramientas). */
  conversar(prompt: string): Promise<RespuestaAgente> {
    return this.invocar<RespuestaAgente>({ prompt });
  }

  /** Acción de un botón: respuesta JSON, sin pasar por el modelo. */
  accion<T>(accion: string, datos: object = {}): Promise<T> {
    return this.invocar<T>({ accion, ...datos });
  }

  private async invocar<T>(payload: object): Promise<T> {
    const response = await this.post(payload);
    const cuerpo = await response.json();
    if (cuerpo?.error) throw new AgenteError(200, cuerpo.error);
    return cuerpo as T;
  }
}

/** Sube el archivo directo a S3 con la URL prefirmada que genera el agente. */
export async function subirAS3(url: string, tipo: string, archivo: File): Promise<void> {
  const response = await fetch(url, { method: "PUT", headers: { "Content-Type": tipo }, body: archivo });
  if (!response.ok) throw new AgenteError(response.status, `S3 rechazó la carga (${response.status})`);
}
