import React from 'react';
import { render } from '@testing-library/react';
import AIAnalysisReport from './AIAnalysisReport';

const mockAnalysisData = {
  dr_grade: 2,
  dr_label: 'Moderate NPDR',
  dr_probability: 0.85,
  dr_all_probabilities: {
    'No DR': 0.05,
    'Mild NPDR': 0.10,
    'Moderate NPDR': 0.85,
    'Severe NPDR': 0.00,
    'Proliferative DR': 0.00,
  },
  label_info: [
    { name: 'no_dr', color: [0, 255, 0] },
    { name: 'mild_npdr', color: [255, 255, 0] },
    { name: 'moderate_npdr', color: [255, 165, 0] },
    { name: 'severe_npdr', color: [255, 100, 0] },
    { name: 'proliferative_dr', color: [255, 0, 0] },
  ],
};

describe('AIAnalysisReport', () => {
  it('renders DR grade correctly', () => {
    const { getByText } = render(<AIAnalysisReport analysisData={mockAnalysisData} />);
    expect(getByText('2')).toBeInTheDocument();
    expect(getByText('Moderate NPDR')).toBeInTheDocument();
  });

  it('renders confidence meter correctly', () => {
    const { getByText } = render(<AIAnalysisReport analysisData={mockAnalysisData} />);
    expect(getByText('85.0%')).toBeInTheDocument();
  });

  it('renders class probabilities correctly', () => {
    const { getByText } = render(<AIAnalysisReport analysisData={mockAnalysisData} />);
    expect(getByText('No DR')).toBeInTheDocument();
    expect(getByText('Mild NPDR')).toBeInTheDocument();
    expect(getByText('Moderate NPDR')).toBeInTheDocument();
    expect(getByText('Severe NPDR')).toBeInTheDocument();
    expect(getByText('Proliferative DR')).toBeInTheDocument();
  });

  it('renders label information correctly', () => {
    const { getByText } = render(<AIAnalysisReport analysisData={mockAnalysisData} />);
    expect(getByText('no_dr')).toBeInTheDocument();
    expect(getByText('mild_npdr')).toBeInTheDocument();
    expect(getByText('moderate_npdr')).toBeInTheDocument();
    expect(getByText('severe_npdr')).toBeInTheDocument();
    expect(getByText('proliferative_dr')).toBeInTheDocument();
  });
});
