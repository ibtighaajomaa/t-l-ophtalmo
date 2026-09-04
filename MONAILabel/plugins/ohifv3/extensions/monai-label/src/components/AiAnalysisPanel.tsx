import React, { Component } from 'react';
import PropTypes from 'prop-types';
import './AiAnalysisPanel.css';
import MonaiLabelClient from '../services/MonaiLabelClient';

export default class AiAnalysisPanel extends Component {
  static propTypes = {
    commandsManager: PropTypes.any,
    servicesManager: PropTypes.any,
    extensionManager: PropTypes.any,
  };

  constructor(props) {
    super(props);
    this.state = {
      loading: false,
      error: null,
      report: null,
      reportsByEye: {},
      activeEye: 'right',
      pollingSavedAnalysis: false,
      generatingReport: false,
      reportResult: null,
      reportResultsByEye: {},
      summaryReportResult: null,
      savedMedicalReportHtml: '',
      reportGenerationStatus: null,
      reportGenerationError: '',
      reportError: null,
      savingReport: false,
      savingSegmentationCorrection: false,
      expandedDrModelsByEye: { right: false, left: false },
    };
    this.serverURI = (typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1') + '/monai/';
  }

  client = () => new MonaiLabelClient(this.serverURI);
  rightColumnRef = React.createRef();
  leftColumnRef = React.createRef();
  reportEditorRef = React.createRef();
  _pollTimeout: any = null;

  componentDidMount() {
    window.addEventListener('teleophtalmo:ai-eye-selected', this.handleEyeSelected);
    window.addEventListener('focus', this.loadSavedAnalysis);
    this.loadSavedAnalysis();
  }

  componentWillUnmount() {
    window.removeEventListener('teleophtalmo:ai-eye-selected', this.handleEyeSelected);
    window.removeEventListener('focus', this.loadSavedAnalysis);
  }

  handleEyeSelected = event => {
    const eye = event?.detail?.eye;
    if (eye === 'right' || eye === 'left') {
      this.selectEye(eye);
    }
  };

  selectEye = eye => {
    if (eye !== 'right' && eye !== 'left') return;
    this.setState({ activeEye: eye }, () => {
      const ref = eye === 'right' ? this.rightColumnRef : this.leftColumnRef;
      ref.current?.scrollIntoView?.({
        behavior: 'smooth',
        block: 'nearest',
        inline: 'nearest',
      });
    });
  };

  getActiveReport = () => {
    const { report, reportsByEye, activeEye } = this.state;
    if (reportsByEye?.[activeEye]) {
      return reportsByEye[activeEye];
    }
    if (report && this.sideFromReport(report) === activeEye) {
      return report;
    }
    return null;
  };

  getActiveGeneratedReport = () => {
    const { reportResult, reportResultsByEye, activeEye } = this.state;
    return reportResultsByEye?.[activeEye] || reportResult;
  };

  isPerEyeAnalysis = value =>
    value &&
    typeof value === 'object' &&
    ('right' in value || 'left' in value) &&
    !('dr_classification' in value);

  sideFromReport = report => {
    const laterality = String(report?.eye_laterality?.laterality || report?.laterality || '').toUpperCase();
    if (laterality === 'R' || laterality === 'RIGHT' || laterality === 'OD') return 'right';
    if (laterality === 'L' || laterality === 'LEFT' || laterality === 'OS' || laterality === 'OG') return 'left';
    return this.state.activeEye;
  };

  normalizeAnalysis = analysis => {
    if (this.isPerEyeAnalysis(analysis)) {
      return {
        reportsByEye: {
          ...(analysis.right ? { right: analysis.right } : {}),
          ...(analysis.left ? { left: analysis.left } : {}),
        },
        activeEye: analysis.right ? 'right' : 'left',
        report: null,
      };
    }
    const side = this.sideFromReport(analysis);
    return {
      reportsByEye: { [side]: analysis },
      activeEye: side,
      report: analysis,
    };
  };

  getAuthToken = () => {
    if (typeof window !== 'undefined') {
      return (
        localStorage.getItem('teleoph.token') ||
        sessionStorage.getItem('teleoph.token')
      );
    }
    return null;
  };

  normalizeMedicalReportHtml = content => {
    const value = String(content || '').trim();
    if (!value) return '';
    if (/<(h[1-6]|p|ul|ol|li|br|strong|b|em|i|u|div|section)\b/i.test(value)) {
      return value.replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, '');
    }
    return value.replace(/\n/g, '<br />');
  };

  getMedicalReportContent = report =>
    report?.final_content || report?.doctor_content || report?.ai_content || '';

  getActiveViewportInfo = () => {
    const { viewportGridService, displaySetService } =
      this.props.servicesManager.services;
    const { viewports, activeViewportId } = viewportGridService.getState();
    const viewport = viewports.get(activeViewportId);
    if (!viewport) return null;
    const displaySet = displaySetService.getDisplaySetByUID(
      viewport.displaySetInstanceUIDs[0]
    );
    return { viewport, displaySet };
  };

  runAnalysis = async () => {
    const { uiNotificationService } = this.props.servicesManager.services;
    this.setState({
      loading: true,
      error: null,
      report: null,
      reportsByEye: {},
      reportResult: null,
      reportResultsByEye: {},
      summaryReportResult: null,
      reportGenerationStatus: null,
      reportGenerationError: '',
    });

    const viewportInfo = this.getActiveViewportInfo();
    if (!viewportInfo || !viewportInfo.displaySet) {
      this.setState({ loading: false, error: 'No active image' });
      return;
    }

    const imageUid = viewportInfo.displaySet.SeriesInstanceUID;
    const studyUid = viewportInfo.displaySet.StudyInstanceUID;
    if (!imageUid || !studyUid) {
      this.setState({
        loading: false,
        error: 'The active viewport is missing its Study or Series Instance UID',
      });
      return;
    }
    const nid = uiNotificationService.show({
      title: 'AI Analysis',
      message: 'Running analysis pipeline...',
      type: 'info',
      duration: 60000,
    });

    try {
      const response = await fetch('/api/exams/run-analysis/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ study_instance_uid: studyUid }),
      });
      const data = await response.json().catch(() => ({}));
      console.log('Analysis response:', data);

      if (!response.ok) {
        throw new Error(data?.detail || data?.error || 'Analysis failed');
      }

      if (data.study_instance_uid && data.study_instance_uid !== studyUid) {
        throw new Error('Analysis response does not match the active study');
      }
      const normalized = this.normalizeAnalysis(data.analysis || data);
      this.setState({
        ...normalized,
        reportResultsByEye: data.reports_by_eye || {},
        reportGenerationStatus: data.report_generation_status || null,
        reportGenerationError: data.report_generation_error || '',
        loading: false,
      });

      uiNotificationService.show({
        title: 'AI Analysis',
        message: 'Analysis complete',
        type: 'success',
        duration: 4000,
      });

      if (data.report_generation_status === 'pending') {
        this.pollSavedAnalysis();
      }
    } catch (err) {
      console.error('Analysis error:', err);
      this.setState({ loading: false, error: err.message || 'Analysis failed' });
      uiNotificationService.show({
        title: 'AI Analysis',
        message: err.message || 'Analysis failed',
        type: 'error',
        duration: 6000,
      });
    } finally {
      uiNotificationService.hide(nid);
    }
  };

  pollSavedAnalysis = () => {
    if (this._pollTimeout) {
      clearTimeout(this._pollTimeout);
    }
    this._pollTimeout = setTimeout(async () => {
      await this.loadSavedAnalysis();
      if (this.state.reportGenerationStatus === 'pending') {
        this.pollSavedAnalysis();
      }
    }, 5000);
  };

  loadSavedAnalysis = async () => {
    const viewportInfo = this.getActiveViewportInfo();
    const studyUid = viewportInfo?.displaySet?.StudyInstanceUID;
    if (!studyUid) return;

    this.setState({ pollingSavedAnalysis: true });
    try {
      const token = this.getAuthToken();
      const response = await fetch(
        `/api/exams/analysis/?study_instance_uid=${encodeURIComponent(studyUid)}`,
        {
          headers: {
            ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
          },
        }
      );
      if (!response.ok) {
        this.setState({ pollingSavedAnalysis: false });
        return;
      }
      const data = await response.json();
      const normalized = this.normalizeAnalysis(data.analysis || data);
      const reportGenerationStatus = data.report_generation_status || null;
      let medicalReport = data.medical_report;
      if (!medicalReport && reportGenerationStatus === 'completed') {
        const reportLookup = await this.loadMedicalReportForStudy(studyUid, token);
        medicalReport = reportLookup;
      }
      const savedMedicalReportHtml = reportGenerationStatus === 'completed'
        ? this.normalizeMedicalReportHtml(this.getMedicalReportContent(medicalReport))
        : '';
      this.setState({
        ...normalized,
        reportResultsByEye: data.reports_by_eye || {},
        summaryReportResult: data.summary_report || null,
        savedMedicalReportHtml,
        reportGenerationStatus,
        reportGenerationError: data.report_generation_error || '',
        pollingSavedAnalysis: false,
      });
    } catch (err) {
      console.debug('Saved analysis unavailable:', err);
      this.setState({ pollingSavedAnalysis: false });
    }
  };

  loadMedicalReportForStudy = async (studyUid, token) => {
    const response = await fetch(
      `/api/exams/medical-reports/?examination_id=${encodeURIComponent(studyUid)}&limit=1`,
      {
        headers: {
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
      }
    );
    if (!response.ok) return null;
    const reports = await response.json().catch(() => []);
    return Array.isArray(reports) ? reports[0] : null;
  };

  generateReport = async (reportOverride = null) => {
    const { uiNotificationService } = this.props.servicesManager.services;
    const report = reportOverride || this.getActiveReport();

    if (!report) {
      this.setState({ reportError: 'No analysis results available. Run AI Analysis first.' });
      return;
    }

    this.setState({ generatingReport: true, reportError: null, reportResult: null });

    const viewportInfo = this.getActiveViewportInfo();
    const patientId = viewportInfo?.displaySet?.PatientID || viewportInfo?.displaySet?.PatientName || 'Unknown';
    const studyUid = viewportInfo?.displaySet?.StudyInstanceUID;
    const seriesUid = viewportInfo?.displaySet?.SeriesInstanceUID;

    const nid = uiNotificationService.show({
      title: 'Report Generation',
      message: 'Queueing medical report generation...',
      type: 'info',
      duration: 120000,
    });

    try {
      const token = this.getAuthToken();
      const response = await fetch('/api/exams/generate-report/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          report_data: report,
          patient_id: patientId,
          study_instance_uid: studyUid,
          series_uid: seriesUid,
        }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.error || `HTTP ${response.status}`);
      }

      const result = await response.json();
      if (response.status === 202 || result.status === 'queued') {
        this.setState({
          generatingReport: false,
          reportGenerationStatus: result.report_generation_status || 'pending',
          reportGenerationError: '',
        });
        uiNotificationService.show({
          title: 'Report Generation',
          message: 'Medical report generation queued',
          type: 'success',
          duration: 4000,
        });
        this.pollSavedAnalysis();
        return;
      }

      this.setState(state => ({
        reportResult: result,
        reportResultsByEye: {
          ...state.reportResultsByEye,
          [state.activeEye]: result,
        },
        generatingReport: false,
      }));

      uiNotificationService.show({
        title: 'Report Generation',
        message: 'Medical report generated successfully',
        type: 'success',
        duration: 4000,
      });
    } catch (err) {
      console.error('Report generation error:', err);
      this.setState({ generatingReport: false, reportError: err.message || 'Report generation failed' });
      uiNotificationService.show({
        title: 'Report Generation',
        message: err.message || 'Report generation failed',
        type: 'error',
        duration: 6000,
      });
    } finally {
      uiNotificationService.hide(nid);
    }
  };

  toggleLesionEraser = () => {
    try {
      this.props.commandsManager.runCommand('toggleSegmentationEraser');
    } catch (err) {
      this.setState({
        reportError: "Impossible d'activer la gomme de segmentation.",
      });
    }
  };

  saveSegmentationCorrectionAndRegenerate = async () => {
    const { uiNotificationService } = this.props.servicesManager.services;
    const activeEye = this.state.activeEye;

    this.setState({
      savingSegmentationCorrection: true,
      reportError: null,
      reportGenerationStatus: null,
      reportGenerationError: '',
    });

    try {
      const result = await this.props.commandsManager.runCommand('saveSegmentationCorrections');
      const normalized = this.normalizeAnalysis(result?.analysis || result);
      const correctedReport =
        normalized.reportsByEye?.[activeEye] ||
        normalized.report ||
        this.getActiveReport();

      this.setState({
        ...normalized,
        activeEye,
        savingSegmentationCorrection: false,
        savedMedicalReportHtml: '',
        summaryReportResult: null,
      });

      await this.generateReport(correctedReport);
    } catch (err) {
      this.setState({
        savingSegmentationCorrection: false,
        reportError: err.message || "Échec de la sauvegarde de la correction.",
      });
      uiNotificationService.show({
        title: 'Corrections',
        message: err.message || "Échec de la sauvegarde de la correction.",
        type: 'error',
        duration: 5000,
      });
    }
  };

  applyReportFormat = (command, value = null) => {
    this.reportEditorRef.current?.focus();
    document.execCommand(command, false, value);
  };

  promptForReportLink = () => {
    const url = window.prompt('Enter the link URL');
    if (url) {
      this.applyReportFormat('createLink', url);
    }
  };

  renderEditorToolbar = () => {
    const commandButton = (label, command, title = label) => (
      <button
        type='button'
        className='editorToolbarButton'
        title={title}
        onMouseDown={event => {
          event.preventDefault();
          this.applyReportFormat(command);
        }}
      >
        {label}
      </button>
    );

    return (
      <div className='editorToolbar' role='toolbar' aria-label='Mise en forme du rapport'>
        <select
          className='editorFormatSelect'
          aria-label='Format du texte'
          defaultValue='p'
          onChange={event => this.applyReportFormat('formatBlock', event.target.value)}
        >
          <option value='p'>Paragraphe</option>
          <option value='h2'>Titre 1</option>
          <option value='h3'>Titre 2</option>
        </select>
        {commandButton(<strong>B</strong>, 'bold', 'Gras')}
        {commandButton(<em>I</em>, 'italic', 'Italique')}
        {commandButton(<u>U</u>, 'underline', 'Souligné')}
        {commandButton(<s>S</s>, 'strikeThrough', 'Barré')}
        {commandButton('1.', 'insertOrderedList', 'Liste numérotée')}
        {commandButton('•', 'insertUnorderedList', 'Liste à puces')}
        {commandButton('≡', 'justifyLeft', 'Aligner à gauche')}
        {commandButton('≣', 'justifyCenter', 'Centrer')}
        {commandButton('☰', 'justifyRight', 'Aligner à droite')}
        {commandButton('←', 'outdent', 'Diminuer le retrait')}
        {commandButton('→', 'indent', 'Augmenter le retrait')}
        {commandButton('Tx', 'removeFormat', 'Effacer la mise en forme')}
        {commandButton('↶', 'undo', 'Annuler')}
        {commandButton('↷', 'redo', 'Rétablir')}
        <button
          type='button'
          className='editorToolbarButton'
          title='Insérer un lien'
          onMouseDown={event => {
            event.preventDefault();
            this.promptForReportLink();
          }}
        >
          🔗
        </button>
        {commandButton('⛓', 'unlink', 'Supprimer le lien')}
        <button
          type='button'
          className='editorToolbarButton editorColorButton'
          title='Texte rouge'
          aria-label='Appliquer la couleur rouge'
          onMouseDown={event => {
            event.preventDefault();
            this.applyReportFormat('foreColor', '#d66a6a');
          }}
        >
          A <span className='editorColorSwatch' />
        </button>
      </div>
    );
  };

  saveReport = async () => {
    const { uiNotificationService } = this.props.servicesManager.services;
    const report = this.getActiveReport();
    const reportResult = this.getActiveGeneratedReport();
    const viewportInfo = this.getActiveViewportInfo();
    const displaySet = viewportInfo?.displaySet;

    if (!reportResult || !displaySet?.SeriesInstanceUID) {
      this.setState({ reportError: 'No generated report or active examination to save.' });
      return;
    }

    this.setState({ savingReport: true, reportError: null });

    try {
      const token = this.getAuthToken();
      const response = await fetch('/api/exams/medical-reports/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          patient_id: displaySet.PatientID || displaySet.PatientName || 'Unknown',
          examination_id: displaySet.SeriesInstanceUID,
          study_instance_uid: displaySet.StudyInstanceUID,
          ai_content: this.reportEditorRef.current?.innerHTML || reportResult.report_html || reportResult.report_text || '',
          ai_report_data: report,
        }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.error || `HTTP ${response.status}`);
      }

      this.setState(state => {
        const reportResultsByEye = { ...state.reportResultsByEye };
        delete reportResultsByEye[state.activeEye];
        return {
          savingReport: false,
          reportResult: null,
          reportResultsByEye,
        };
      });
      uiNotificationService.show({
        title: 'Report Saved',
        message: 'Medical report saved and examination marked as interpreted',
        type: 'success',
        duration: 4000,
      });
    } catch (err) {
      console.error('Report save error:', err);
      this.setState({
        savingReport: false,
        reportError: err.message || 'Report save failed',
      });
      uiNotificationService.show({
        title: 'Report Save',
        message: err.message || 'Report save failed',
        type: 'error',
        duration: 6000,
      });
    }
  };

  getDrProbabilities = (dr, report = {}) => {
    const classes = [
      { label: 'Pas de RD', color: '#4caf66', aliases: ['no dr', 'no_dr', '0'] },
      { label: 'RDNP légère', color: '#8bc34a', aliases: ['mild npdr', 'mild_npdr', '1'] },
      { label: 'RDNP modérée', color: '#f2b705', aliases: ['moderate npdr', 'moderate_npdr', '2'] },
      { label: 'RDNP sévère', color: '#ff7a1a', aliases: ['severe npdr', 'severe_npdr', '3'] },
      { label: 'RD proliférante', color: '#ef4444', aliases: ['proliferative dr', 'proliferative_dr', '4'] },
    ];
    const normalizeLabel = label =>
      String(label || '')
        .trim()
        .toLowerCase()
        .replace(/[_-]+/g, ' ')
        .replace(/\s+/g, ' ');
    const toEntries = probabilities => {
      if (Array.isArray(probabilities)) {
        return probabilities.map(item => [
          item.label ?? item.class ?? item.name,
          item.score ?? item.probability ?? item.value,
        ]);
      }
      return Object.entries(probabilities || {});
    };
    const probabilitySources = [
      dr.probabilities,
      dr.dr_all_probabilities,
      report.probabilities,
      report.dr_all_probabilities,
    ];
    const probabilityEntries =
      probabilitySources.map(toEntries).find(entries => entries.length > 0) || [];
    const scores = new Map(
      probabilityEntries.map(([label, score]) => [normalizeLabel(label), Number(score) || 0])
    );
    const predictedLabel = normalizeLabel(dr.grade ?? dr.label ?? dr.predicted_grade);

    return classes.map(item => {
      const aliases = [item.label, ...item.aliases].map(normalizeLabel);
      const rawScore = aliases.map(alias => scores.get(alias)).find(score => score !== undefined) || 0;
      const score = rawScore > 1 ? rawScore / 100 : rawScore;
      return {
        ...item,
        isPredicted: aliases.includes(predictedLabel),
        percentage: Math.max(0, Math.min(100, Math.round(score * 100))),
      };
    });
  };

  renderDrModelCard = (title, model, report = {}) => {
    if (!model) return null;
    const available = model.status === 'ok';
    const confidence = Number(model.confidence) || 0;
    const confidencePercentage = Math.round(
      Math.max(0, Math.min(1, confidence > 1 ? confidence / 100 : confidence)) * 100
    );
    const probabilities = this.getDrProbabilities(model, report);

    return (
      <div
        style={{
          flex: '1 1 220px',
          minWidth: 0,
          padding: '10px',
          border: `1px solid ${available ? '#0ea5e9' : '#64748b'}`,
          borderRadius: '7px',
          background: '#0f172a',
        }}
      >
        {available ? (
          <>
            <div className="drPrediction">
              <span className="label">Grade</span>
              <span className="gradeValue">
                {probabilities.find(item => item.isPredicted)?.label || model.grade || 'Inconnu'}
              </span>
              <span className="drPredictionPercentage">{confidencePercentage}%</span>
            </div>
            <div className="drProbabilityList">
              {probabilities.map(item => (
                <div className="drProbabilityRow" key={`${title}-${item.label}`}>
                  <span className={`drProbabilityLabel ${item.isPredicted ? 'predicted' : ''}`}>
                    {item.label}
                  </span>
                  <div
                    className="drProbabilityTrack"
                    role="progressbar"
                    aria-label={`${title} ${item.label}`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={item.percentage}
                    style={{
                      backgroundColor: `${item.color}4d`,
                      boxShadow: `inset 0 0 0 1px ${item.color}80`,
                    }}
                  >
                    <div
                      className={`drProbabilityFill ${item.isPredicted ? 'predicted' : ''}`}
                      style={{
                        width: `${item.percentage}%`,
                        minWidth: item.percentage > 0 ? '3px' : '6px',
                        backgroundColor: item.color,
                      }}
                    />
                  </div>
                  <span className={`drProbabilityPercentage ${item.isPredicted ? 'predicted' : ''}`}>
                    {item.percentage}%
                  </span>
                </div>
              ))}
            </div>

          </>
        ) : (
          <div style={{ color: '#fbbf24', fontSize: '12px' }}>
            Indisponible{model.reason ? ` — ${model.reason}` : ''}
          </div>
        )}
      </div>
    );
  };

  getReportForSide = side => {
    const { report, reportsByEye } = this.state;
    if (reportsByEye?.[side]) {
      return reportsByEye[side];
    }

    if (!report) {
      return null;
    }

    return this.sideFromReport(report) === side ? report : null;
  };

  getGeneratedReportForSide = side => this.state.reportResultsByEye?.[side] || null;

  renderEyeToggles = () => {
    const { activeEye, reportsByEye } = this.state;
    const eyeButton = (side, label) => {
      return (
        <button
          type="button"
          className={`eyeToggleButton${activeEye === side ? ' active' : ''}`}
          onClick={() => this.selectEye(side)}
          aria-pressed={activeEye === side}
        >
          {label}
        </button>
      );
    };

    if (!reportsByEye || Object.keys(reportsByEye).length === 0) {
      return null;
    }

    return (
      <div className="eyeToggleSection">
        <div className="eyeToggleContainer" aria-label="Navigation par œil">
          {eyeButton('right', 'Œil droit')}
          {eyeButton('left', 'Œil gauche')}
        </div>
      </div>
    );
  };

  openReportEditor = side => {
    const generatedReport = this.getGeneratedReportForSide(side);
    if (!generatedReport) return;
    this.setState({
      activeEye: side,
      reportResult: generatedReport,
      reportError: null,
    });
  };

  renderGeneratedReportPreview = side => {
    const generatedReport = this.getGeneratedReportForSide(side);
    if (!generatedReport) {
      return (
        <div className="section generatedReportPreview pending">
          <div className="sectionTitle">Rapport IA</div>
          Rapport automatique en attente...
        </div>
      );
    }

    const html =
      generatedReport.report_html ||
      String(generatedReport.report_text || '').replace(/\n/g, '<br />');

    return (
      <div className="section generatedReportPreview">
        <div className="sectionTitle">Rapport IA</div>
        <div
          className="storedReportContent"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      </div>
    );
  };

  renderEyePlaceholder = side => (
    <div className="eyePlaceholder">
      <div className="spinner small" />
      Résultat {side === 'right' ? 'œil droit' : 'œil gauche'} en attente...
    </div>
  );

  renderEyeColumn = side => {
    const report = this.getReportForSide(side);
    const isActive = this.state.activeEye === side;
    const label = side === 'right' ? 'Œil droit' : 'Œil gauche';
    const ref = side === 'right' ? this.rightColumnRef : this.leftColumnRef;

    return (
      <section
        ref={ref}
        className={`eyeReportColumn${isActive ? ' active' : ''}`}
        aria-label={`Rapport ${label}`}
      >
        <div className="eyeColumnHeader">
          <span>{label}</span>
          {isActive && <span className="activeEyeBadge">sélectionné</span>}
        </div>
        {report ? this.renderReport(report, side) : this.renderEyePlaceholder(side)}
      </section>
    );
  };

  renderDeepSeeNet = report => {
    const deepseenet = report?.deepseenet_plus;
    if (!deepseenet) return null;

    const factors = [
      ['Drusen', deepseenet.drusen],
      ['Anomalies pigmentaires', deepseenet.pigment],
      ['DMLA avancée', deepseenet.amd],
    ];
    const labelMap = {
      none_small: 'Absents / petits',
      intermediate: 'Intermédiaires',
      large: 'Larges',
      absent: 'Absente',
      present: 'Présentes',
      advanced: 'Présente',
    };
    const patient = deepseenet.patient_summary || {};
    const modes = factors
      .map(([, factor]) => factor?.preprocessing_mode)
      .filter(Boolean);
    const usedFallback = modes.includes('central_crop_fallback');

    return (
      <div className="section" style={{ borderColor: '#fb7185' }}>
        <div className="sectionTitle" style={{ color: '#fda4af' }}>
          DMLA
        </div>
        {factors.map(([title, factor]) => factor && (
          <div className="row" key={title}>
            <span className="label">{title}</span>
            <span
              className="value"
              style={{
                color:
                  factor.label === 'advanced' || factor.label === 'large'
                    ? '#fb7185'
                    : factor.label === 'present' || factor.label === 'intermediate'
                      ? '#fbbf24'
                      : '#86efac',
              }}
            >
              {labelMap[factor.label] || factor.label} — {Math.round((Number(factor.probability) || 0) * 100)}%
            </span>
          </div>
        ))}
        <div className="row" style={{ marginTop: '8px', borderTop: '1px solid #475569', paddingTop: '8px' }}>
          <span className="label">Score AREDS bilatéral</span>
          <span className="value" style={{ color: '#fda4af', fontWeight: 700 }}>
            {patient.simplified_score === null || patient.simplified_score === undefined
              ? 'Non calculable'
              : `${patient.simplified_score}/5`}
          </span>
        </div>

      </div>
    );
  };

  renderReport = (report, side = null) => {
    if (!report) return null;

    const dr = report.dr_classification || {};
    const drModels = report.dr_classification_models || {};
    const clipDr = drModels.clip_dr || null;
    const modelEntries = [
      ['clip_dr', 'CLIP-DR', clipDr || {
        status: 'unavailable', grade: 'Unknown', confidence: 0, probabilities: {},
        reason: 'Résultat CLIP-DR non disponible dans cet ancien rapport',
      }],
    ];
    const gradeIndex = model => {
      const explicit = Number(model?.grade_index);
      if (Number.isInteger(explicit) && explicit >= 0 && explicit <= 4) return explicit;
      const grade = String(model?.grade || '').toLowerCase().replace(/[_-]/g, ' ');
      if (grade.includes('proliferative')) return 4;
      if (grade.includes('severe')) return 3;
      if (grade.includes('moderate')) return 2;
      if (grade.includes('mild')) return 1;
      if (grade.includes('no dr') || grade.includes('normal')) return 0;
      return -1;
    };
    const availableModels = modelEntries.filter(([, , model]) => model.status === 'ok' && gradeIndex(model) >= 0);
    const fallbackSelected = [...availableModels].sort((a, b) =>
      gradeIndex(b[2]) - gradeIndex(a[2]) ||
      Number(b[2].confidence || 0) - Number(a[2].confidence || 0)
    )[0];
    const persistedKey = report.selected_dr_classification?.model_key;
    const adjudication = report.medgemma_dr_adjudication || null;
    const hasMedGemmaAdjudication = !!adjudication;
    const hasMultimodalMedGemma =
      adjudication?.method === 'medgemma_multimodal_two_stage';
    const adjudicatedGrade = hasMedGemmaAdjudication ? gradeIndex(adjudication) : -1;
    const calculatedClosest = adjudicatedGrade >= 0
      ? [...availableModels].sort((a, b) =>
        Math.abs(gradeIndex(a[2]) - adjudicatedGrade) - Math.abs(gradeIndex(b[2]) - adjudicatedGrade) ||
        gradeIndex(b[2]) - gradeIndex(a[2]) ||
        Number(b[2].confidence || 0) - Number(a[2].confidence || 0)
      )[0]
      : null;
    const closestKey = report.closest_dr_model?.model_key;
    const selectedModel = (
      hasMedGemmaAdjudication && modelEntries.find(([key]) => key === closestKey)
    ) || calculatedClosest || modelEntries.find(([key]) => key === persistedKey) || fallbackSelected;
    const exactGradeMatch = !hasMedGemmaAdjudication ||
      (selectedModel && gradeIndex(selectedModel[2]) === adjudicatedGrade);
    const classifierGrades = availableModels.map(([, , model]) => gradeIndex(model));
    const medGemmaMatches = hasMedGemmaAdjudication &&
      classifierGrades.some(modelGrade => modelGrade === adjudicatedGrade);
    const classifiersAgree = classifierGrades.length > 1 &&
      classifierGrades.every(modelGrade => modelGrade === classifierGrades[0]);
    const concordanceLabel = !hasMedGemmaAdjudication
      ? null
      : !hasMultimodalMedGemma
        ? 'MedGemma indisponible — résultat de repli'
        : medGemmaMatches && classifiersAgree
          ? 'Concordance complète'
          : medGemmaMatches
            ? 'Concordance partielle'
            : 'Discordance';
    const reviewRequired = hasMedGemmaAdjudication && (
      adjudication.requires_ophthalmologist_review ||
      adjudication.status !== 'supported' ||
      !hasMultimodalMedGemma ||
      !medGemmaMatches
    );
    const lesions = report.lesions || {};
    const vessels = report.vessels || {};
    const glaucoma = report.glaucoma || {};
    const eyeLaterality = report.eye_laterality || {};
    const eyeLabel = side === 'right'
      ? 'ŒIL DROIT'
      : side === 'left'
        ? 'ŒIL GAUCHE'
        : eyeLaterality.laterality === 'R'
          ? 'ŒIL DROIT'
          : eyeLaterality.laterality === 'L'
            ? 'ŒIL GAUCHE'
            : null;
    return (
      <div className="eyeReportContent">
        <div className="reportTitle">
          Rapport d'analyse par AI{eyeLabel ? ` (${eyeLabel})` : ''}
          {lesions.doctor_corrected && (
            <span className="lesionCorrectionBadge" style={{ marginLeft: '8px' }}>
              ✓ Confirmé par le médecin
            </span>
          )}
        </div>

        {hasMedGemmaAdjudication && (
          <div className="section medGemmaResultCard" aria-label="Résultat MedGemma">
            <div className="sectionTitle">Résultat MedGemma</div>
            <div className="medGemmaResultField">
              <span className="medGemmaResultLabel">Grade :</span>
              <span className="medGemmaGrade">
                {String(adjudication.grade || 'Unknown').replace(/_/g, ' ')}
              </span>
            </div>
          </div>
        )}

        {(dr.grade || clipDr) && (
          <div className="section drClassification">
            <div className="sectionTitle">Classification de la rétinopathie diabétique</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
              {modelEntries.map(([key, title, model]) => (
                <React.Fragment key={key}>
                  {this.renderDrModelCard(title, model, report)}
                </React.Fragment>
              ))}
              {hasMedGemmaAdjudication && !exactGradeMatch && (
                <div style={{ width: '100%', color: '#fbbf24', fontSize: '10px' }}>
                  Aucun classifieur ne prédit exactement le grade proposé par MedGemma.
                </div>
              )}
            </div>
          </div>
        )}

        {side && this.renderGeneratedReportPreview(side)}

        {this.renderDeepSeeNet(report)}

        {(lesions.microaneurysms !== undefined || lesions.hemorrhages !== undefined || lesions.hard_exudates !== undefined) && (
          <div className="section">
            <div className="sectionTitle">Lésions</div>
            {lesions.doctor_corrected && (
              <div className="lesionCorrectionBadge">Correction médecin appliquée</div>
            )}
            <div className="row">
              <span className="label">Microanévrismes</span>
              <span className="value">{lesions.microaneurysms ?? 0}</span>
            </div>
            <div className="row">
              <span className="label">Hémorragies</span>
              <span className="value">{lesions.hemorrhages ?? 0}</span>
            </div>
            <div className="row">
              <span className="label">Exsudats</span>
              <span className="value">
                {lesions.hard_exudates ?? lesions.exudates ?? 0}
              </span>
            </div>
            <div className="row">
              <span className="label">Nodules cotonneux</span>
              <span className="value">{lesions.soft_exudates ?? lesions.cotton_wool_spots ?? 0}</span>
            </div>
            <div className="row">
              <span className="label">Néovascularisation</span>
              <span className="value">{lesions.neovascularization ?? 0}</span>
            </div>
            {lesions.coverage_pct !== undefined && (
              <div className="row">
                <span className="label">Couverture</span>
                <span className="value">{lesions.coverage_pct.toFixed(1)}%</span>
              </div>
            )}
          </div>
        )}

        {glaucoma.vcdr !== undefined && (
          <div className="section">
            <div className="sectionTitle" style={{ textTransform: 'uppercase' }}>Évaluation du glaucome</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '8px' }}>
              <div style={{ background: '#1c1f27', padding: '8px', borderRadius: '4px' }}>
                <div style={{ fontSize: '11px', color: '#888', textTransform: 'uppercase' }}>VCDR</div>
                <div style={{ fontSize: '16px', fontWeight: 'bold', color: '#fff', marginTop: '4px' }}>
                  {glaucoma.vcdr.toFixed(4)}
                </div>
              </div>
              <div style={{ background: '#1c1f27', padding: '8px', borderRadius: '4px' }}>
                <div style={{ fontSize: '11px', color: '#888', textTransform: 'uppercase' }}>Risque</div>
                <div style={{ fontSize: '16px', fontWeight: 'bold', marginTop: '4px', color: glaucoma.risk === 'Eleve' ? '#ef5350' : (glaucoma.risk === 'Modere' ? '#ffa726' : '#66bb6a') }}>
                  {glaucoma.risk}
                </div>
              </div>
              <div style={{ background: '#1c1f27', padding: '8px', borderRadius: '4px' }}>
                <div style={{ fontSize: '11px', color: '#888', textTransform: 'uppercase' }}>Surface du disque</div>
                <div style={{ fontSize: '14px', fontWeight: 'bold', color: '#fff', marginTop: '4px' }}>
                  {glaucoma.disc_area_px || '—'} px
                </div>
              </div>
              <div style={{ background: '#1c1f27', padding: '8px', borderRadius: '4px' }}>
                <div style={{ fontSize: '11px', color: '#888', textTransform: 'uppercase' }}>Surface de l'excavation</div>
                <div style={{ fontSize: '14px', fontWeight: 'bold', color: '#fff', marginTop: '4px' }}>
                  {glaucoma.cup_area_px || '—'} px
                </div>
              </div>
            </div>
          </div>
        )}

        {vessels.Coverage_pct !== undefined && (
          <div className="section">
            <div className="sectionTitle">Vessels</div>
            <div className="row">
              <span className="label">Coverage</span>
              <span className="value">{vessels.Coverage_pct.toFixed(1)}%</span>
            </div>
            {vessels.tortuosity !== undefined && (
              <div className="row">
                <span className="label">Tortuosity</span>
                <span className="value">{vessels.tortuosity.toFixed(3)}</span>
              </div>
            )}
          </div>
        )}

        {report.gradcam_image && (
          <div className="section" style={{ marginTop: '16px' }}>
            <div className="sectionTitle">Grad-CAM Visualization</div>
            <img
              src={`data:image/png;base64,${report.gradcam_image}`}
              alt="Grad-CAM Visualization"
              style={{ width: '100%', borderRadius: '4px', marginTop: '8px' }}
            />
          </div>
        )}

        {report.clahe_image && (
          <div className="section" style={{ marginTop: '16px' }}>
            <div className="sectionTitle">Améliorée par CLAHE</div>
            <img
              src={`data:image/png;base64,${report.clahe_image}`}
              alt="Améliorée par CLAHE"
              style={{ width: '100%', borderRadius: '4px', marginTop: '8px' }}
            />
          </div>
        )}
      </div>
    );
  };

  render() {
    const {
      loading,
      error,
      reportError,
      savingReport,
      reportsByEye,
      activeEye,
      pollingSavedAnalysis,
    } = this.state;
    const activeReport = this.getActiveReport();
    const { savedMedicalReportHtml, summaryReportResult } = this.state;
    const reportResult = summaryReportResult || (savedMedicalReportHtml
      ? { report_html: savedMedicalReportHtml, report_text: '' }
      : this.state.reportResult);
    const hasAnyReport =
      !!activeReport || !!savedMedicalReportHtml || Object.keys(reportsByEye || {}).length > 0;

    return (
      <div className="aiAnalysisPanel">
        {!hasAnyReport && !loading && !pollingSavedAnalysis && !error && (
          <div className="loading compact">
            <div className="spinner" />
            Classification automatique en attente...
          </div>
        )}

        {(loading || pollingSavedAnalysis) && !activeReport && (
          <div className="loading">
            <div className="spinner" />
            {loading ? 'Running AI analysis...' : 'Classification automatique en cours...'}<br />
            <small>Segmentation → Classification → Quantification</small>
          </div>
        )}

        {error && (
          <div>
            <div className="error">{error}</div>
          </div>
        )}

        {hasAnyReport && (
          <div>
            {this.renderEyeToggles()}
            <div className="perEyeReportGrid">
              {this.renderEyeColumn('right')}
              {this.renderEyeColumn('left')}
            </div>

            {reportError && (
              <div className="error" style={{ marginTop: '16px' }}>
                {reportError}
              </div>
            )}

            {reportResult && (
              <div className="generatedReport">
                <h3 className="generatedReportTitle">Rapport médical généré</h3>
                {this.renderEditorToolbar()}
                <div
                  ref={this.reportEditorRef}
                  className="reportContent reportEditor"
                  contentEditable
                  suppressContentEditableWarning
                  dangerouslySetInnerHTML={{ __html: reportResult.report_html }}
                />
                <div className="reportValidationNote">
                  Rapport modifiable — vérifiez le contenu clinique avant validation.
                </div>
                <div className="generatedReportActions">
                  <button
                    className="saveReportButton"
                    onClick={this.saveReport}
                    disabled={savingReport}
                  >
                    {savingReport ? 'Enregistrement...' : 'Enregistrer'}
                  </button>
                  <button
                    className="printReportButton"
                    onClick={() => {
                      const printWindow = window.open('', '_blank');
                      printWindow.document.write(`
                        <html>
                          <head><title>Medical Report</title></head>
                          <body>${this.reportEditorRef.current?.innerHTML || reportResult.report_html}</body>
                        </html>
                      `);
                      printWindow.document.close();
                      printWindow.print();
                    }}
                  >
                    Imprimer le rapport
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }
}
