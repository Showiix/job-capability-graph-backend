import { Component, type ErrorInfo, type ReactNode } from 'react';
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
          fontSize: 14,
          controlHeight: 40,
          controlHeightSM: 36,
          lineHeight: 1.5,
        },
        components: {
          Layout: {
            headerBg: '#000000',
          },
          Input: {
            activeBorderColor: '#E4B592',
            hoverBorderColor: '#E4B592',
            colorBgContainer: 'rgba(255,243,234,0.035)',
          },
          Select: {
            optionSelectedBg: 'rgba(238,18,18,0.16)',
            optionActiveBg: 'rgba(255,243,234,0.08)',
            colorBgContainer: 'rgba(255,243,234,0.035)',
          },
          Button: {
            controlHeight: 40,
            contentFontSize: 14,
          },
        },
      }}
    >
      <AppRouter />
    </ConfigProvider>
  );
}

class AppErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error('UI render error', error, info); }
  render() {
    if (this.state.error) return <main style={{ padding: 40, color: '#fff3ea' }}><h1>页面暂时无法显示</h1><p>请刷新页面重试。</p><pre style={{ whiteSpace: 'pre-wrap', color: '#e4b592' }}>{this.state.error.message}</pre></main>;
    return this.props.children;
  }
}

function App() {
  return (
    <ThemeProvider>
      <AuthProvider><AppErrorBoundary><ThemedApp /></AppErrorBoundary></AuthProvider>
    </ThemeProvider>
  );
}

export default App;
