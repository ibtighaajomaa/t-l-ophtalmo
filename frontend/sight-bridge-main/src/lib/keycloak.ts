import Keycloak from 'keycloak-js';

// Configuration Keycloak
const keycloak = new Keycloak({
  url: 'http://localhost:8080/', // L'URL de votre Keycloak (Port 8080)
  realm: 'HopitalRealm',         // Le nom de votre royaume
  clientId: 'hopital-frontend'   // Le nom du client FRONTEND (celui sans secret)
});

export default keycloak;
