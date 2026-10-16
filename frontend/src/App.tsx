import AppLayout from "@cloudscape-design/components/app-layout";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import SideNavigation from "@cloudscape-design/components/side-navigation";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import TopNavigation from "@cloudscape-design/components/top-navigation";
import { useAuth } from "react-oidc-context";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router";
import type { RuntimeConfig } from "./config";
import AlbumPage from "./pages/AlbumPage";
import ChatPage from "./pages/ChatPage";
import DocumentosPage from "./pages/DocumentosPage";

const NAV_ITEMS = [
  { type: "link" as const, text: "Conversación", href: "/chat" },
  { type: "link" as const, text: "Mi álbum", href: "/album" },
  { type: "link" as const, text: "Documentos", href: "/documentos" },
];

function SignIn({ onSignIn, error }: { onSignIn: () => void; error?: string }) {
  return (
    <Box margin="xxxl" textAlign="center">
      <Container header={<Header variant="h1">Parcero · Mundial 2026</Header>}>
        <SpaceBetween size="m">
          <Box>Tu asistente del Mundial 2026 y de tu álbum de láminas, en Amazon Bedrock AgentCore.</Box>
          {error && <Box color="text-status-error">{error}</Box>}
          <Button variant="primary" onClick={onSignIn}>
            Iniciar sesión
          </Button>
        </SpaceBetween>
      </Container>
    </Box>
  );
}

export default function App({ config }: { config: RuntimeConfig }) {
  const auth = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  if (auth.isLoading) {
    return (
      <Box margin="xxxl" textAlign="center">
        <Spinner size="large" />
      </Box>
    );
  }
  if (!auth.isAuthenticated) {
    return <SignIn onSignIn={() => void auth.signinRedirect()} error={auth.error?.message} />;
  }

  const signOut = async () => {
    await auth.removeUser();
    // Cognito cierra su propia sesión en el endpoint /logout del managed login.
    const logoutUri = encodeURIComponent(`${window.location.origin}/`);
    window.location.href = `https://${config.cognitoDomain}/logout?client_id=${config.userPoolClientId}&logout_uri=${logoutUri}`;
  };

  return (
    <>
      <div id="top-nav">
        <TopNavigation
          identity={{ href: "/", title: "Parcero · Mundial 2026" }}
          utilities={[
            {
              type: "menu-dropdown",
              text: String(auth.user?.profile["cognito:username"] ?? auth.user?.profile.email ?? "Usuario"),
              iconName: "user-profile",
              items: [{ id: "signout", text: "Cerrar sesión" }],
              onItemClick: ({ detail }) => {
                if (detail.id === "signout") void signOut();
              },
            },
          ]}
        />
      </div>
      <AppLayout
        headerSelector="#top-nav"
        toolsHide
        navigation={
          <SideNavigation
            activeHref={`/${location.pathname.split("/")[1]}`}
            header={{ href: "/chat", text: "Menú" }}
            items={NAV_ITEMS}
            onFollow={(event) => {
              event.preventDefault();
              navigate(event.detail.href);
            }}
          />
        }
        content={
          <Routes>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/album" element={<AlbumPage />} />
            <Route path="/documentos" element={<DocumentosPage />} />
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Routes>
        }
      />
    </>
  );
}
