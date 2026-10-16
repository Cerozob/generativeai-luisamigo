import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useAuth } from "react-oidc-context";
import { AgenteClient } from "./agente";

const AgenteContext = createContext<AgenteClient | null>(null);

export function AgenteProvider({ url, children }: { url: string; children: ReactNode }) {
  const auth = useAuth();
  const accessToken = auth.user?.access_token;
  // El authorizer JWT de AgentCore valida el access token (claim client_id) del user pool.
  const client = useMemo(() => new AgenteClient(url, () => accessToken), [url, accessToken]);
  return <AgenteContext.Provider value={client}>{children}</AgenteContext.Provider>;
}

export function useAgente(): AgenteClient {
  const client = useContext(AgenteContext);
  if (!client) throw new Error("useAgente debe usarse dentro de AgenteProvider");
  return client;
}
