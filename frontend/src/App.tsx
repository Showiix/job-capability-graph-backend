import { ConfigProvider, theme } from 'antd';
import AppRouter from './routes';
import { ThemeProvider } from './context/ThemeContext';
import { AuthProvider } from './context/AuthContext';

function ThemedApp() {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#EE1212',
          colorBgBase: '#000000',
          colorTextBase: '#FFF3EA',
          colorBorder: 'rgba(255,243,234,0.22)',
          borderRadius: 0,
        },
        components: {
          Layout: {
            headerBg: '#000000',
          },
        },
      }}
    >
      <AppRouter />
    </ConfigProvider>
  );
}

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <ThemedApp />
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
