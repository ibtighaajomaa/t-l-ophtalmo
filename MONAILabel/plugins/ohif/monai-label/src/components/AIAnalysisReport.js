/*
Copyright (c) MONAI Consortium
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
    http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

import React, { Component } from 'react';
import PropTypes from 'prop-types';

import './AIAnalysisReport.styl';

const DR_GRADE_LABELS = {
  0: 'No DR',
  1: 'Mild NPDR',
  2: 'Moderate NPDR',
  3: 'Severe NPDR',
  4: 'Proliferative DR',
};

const DR_COLORS = {
  0: [0, 255, 0],
  1: [255, 255, 0],
  2: [255, 165, 0],
  3: [255, 100, 0],
  4: [255, 0, 0],
};

export default class AIAnalysisReport extends Component {
  static propTypes = {
    analysisData: PropTypes.object,
  };

  constructor(props) {
    super(props);

    this.state = {
      analysisData: props.analysisData || {},
    };
  }

  componentDidUpdate(prevProps) {
    if (prevProps.analysisData !== this.props.analysisData) {
      this.setState({ analysisData: this.props.analysisData });
    }
  }

  render() {
    const { analysisData } = this.state;

    const drGrade = analysisData.dr_grade !== undefined ? analysisData.dr_grade : null;
    const drLabel = analysisData.dr_label || 'N/A';
    const drProbability = analysisData.dr_probability !== undefined ? analysisData.dr_probability : 0;
    const allProbabilities = analysisData.dr_all_probabilities || {};
    const labelInfo = analysisData.label_info || [];

    const getGradeColor = (grade) => {
      const color = DR_COLORS[grade] || [128, 128, 128];
      return `rgba(${color.join(',')})`;
    };

    const getProbabilityColor = (grade) => {
      const color = DR_COLORS[grade] || [128, 128, 128];
      return `rgba(${color.join(',')})`;
    };

    return (
      <div className="aiAnalysisReport">
        <div className="report-header">
          <h3>AI Analysis Report</h3>
        </div>

        <div className="report-content">
          <div className="section">
            <h4>DR Classification</h4>
            <div className="dr-grade-section">
              <div className="grade-display">
                <span
                  className="grade-number"
                  style={{ backgroundColor: drGrade !== null ? getGradeColor(drGrade) : '#ccc' }}
                >
                  {drGrade !== null ? drGrade : '-'}
                </span>
                <span className="grade-label">{drLabel}</span>
              </div>
              <div className="confidence-meter">
                <div className="confidence-label">Confidence</div>
                <div className="confidence-bar-container">
                  <div
                    className="confidence-bar"
                    style={{
                      width: `${drProbability * 100}%`,
                      backgroundColor: drGrade !== null ? getGradeColor(drGrade) : '#ccc',
                    }}
                  />
                </div>
                <div className="confidence-value">{(drProbability * 100).toFixed(1)}%</div>
              </div>
            </div>
          </div>

          <div className="section">
            <h4>Class Probabilities</h4>
            <div className="probabilities-list">
              {Object.entries(allProbabilities).map(([label, probability]) => {
                const grade = DR_GRADE_LABELS[label] !== undefined
                  ? Object.keys(DR_GRADE_LABELS).find(key => DR_GRADE_LABELS[key] === label)
                  : null;
                const color = grade !== null ? getProbabilityColor(grade) : '#ccc';

                return (
                  <div key={label} className="probability-item">
                    <div className="probability-label">
                      <span
                        className="color-dot"
                        style={{ backgroundColor: color }}
                      />
                      <span className="label-name">{label}</span>
                    </div>
                    <div className="probability-bar-container">
                      <div
                        className="probability-bar"
                        style={{
                          width: `${probability * 100}%`,
                          backgroundColor: color,
                        }}
                      />
                      <span className="probability-value">{(probability * 100).toFixed(1)}%</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="section">
            <h4>Label Information</h4>
            <div className="label-info-grid">
              {labelInfo.map((info, index) => {
                const grade = index;
                const color = DR_COLORS[grade] || [128, 128, 128];

                return (
                  <div key={info.name} className="label-info-item">
                    <div
                      className="color-square"
                      style={{ backgroundColor: `rgba(${color.join(',')})` }}
                    />
                    <div className="label-details">
                      <div className="label-name">{info.name}</div>
                      <div className="label-color">RGB: {color.join(', ')}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    );
  }
}
