import Keycloak from 'keycloak-js';

// Configuration Keycloak
const keycloak = new Keycloak({
  url: 'http://193.95.31.196/auth/', // L'URL de votre Keycloak
  realm: 'HopitalRealm',         // Le nom de votre royaume
  clientId: 'hopital-frontend'   // Le nom du client FRONTEND (celui sans secret)
});

export default keycloak;
